/* HLauncher float PCM input. Only a producer thread reads stdin; the PipeWire
 * realtime callback performs bounded copies from a preallocated SPSC ring.
 * No gain, normalization, resampling, allocation, logging or locks in process(). */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>
#define RATE 48000
#define STRIDE 8
#define CAPACITY 9600
#define PREFILL 3840
struct audio {
    struct pw_main_loop *loop;
    struct pw_stream *stream;
    struct spa_source *wake;
    float samples[CAPACITY*2];
    atomic_uint_fast64_t written, read, underrun_frames, underrun_events;
    uint64_t last_callback_ns, max_callback_gap_ns;
    atomic_bool eof, active, stopping;
    atomic_int error;
    bool flushing;
    int ready_fd;
    int capture_fd;
};
static void wake_main(struct audio *a) {
    pw_loop_signal_event(pw_main_loop_get_loop(a->loop), a->wake);
}
static void *produce(void *arg) {
    struct audio *a=arg;
    if(a->ready_fd>=0) {
        char ready;
        ssize_t n;
        do { n=read(a->ready_fd,&ready,1); } while(n<0 && errno==EINTR);
        close(a->ready_fd);
        if(n!=1) { atomic_store(&a->error,1); atomic_store(&a->eof,true); wake_main(a); return NULL; }
    }
    uint8_t raw[32768+STRIDE]; size_t carry=0;
    while (!atomic_load(&a->stopping)) {
        ssize_t n=read(STDIN_FILENO,raw+carry,32768);
        if(n<0 && errno==EINTR) continue;
        if(n<=0) { if(n<0 || carry) atomic_store(&a->error,1); break; }
        size_t bytes=carry+(size_t)n, frames=bytes/STRIDE, offset=0;
        while(offset<frames && !atomic_load(&a->stopping)) {
            uint64_t w=atomic_load_explicit(&a->written,memory_order_relaxed);
            uint64_t r=atomic_load_explicit(&a->read,memory_order_acquire);
            size_t space=CAPACITY-(w-r);
            if(!space) { struct timespec delay={0,1000000}; nanosleep(&delay,NULL); continue; }
            size_t take=SPA_MIN(space,frames-offset), at=w%CAPACITY;
            size_t first=SPA_MIN(take,CAPACITY-at);
            memcpy(a->samples+at*2,raw+offset*STRIDE,first*STRIDE);
            if(take>first) memcpy(a->samples,raw+(offset+first)*STRIDE,(take-first)*STRIDE);
            atomic_store_explicit(&a->written,w+take,memory_order_release);
            offset+=take;
            if(!atomic_load(&a->active) && w+take-r>=PREFILL) wake_main(a);
        }
        carry=bytes%STRIDE;
        memmove(raw,raw+frames*STRIDE,carry);
    }
    atomic_store_explicit(&a->eof,true,memory_order_release);
    wake_main(a);
    return NULL;
}
static void *capture_write(void *arg) {
    struct audio *a=arg;
    while(true) {
        uint64_t r=atomic_load_explicit(&a->read,memory_order_relaxed);
        uint64_t w=atomic_load_explicit(&a->written,memory_order_acquire);
        if(r==w) {
            if(atomic_load(&a->stopping)) break;
            struct timespec delay={0,1000000}; nanosleep(&delay,NULL); continue;
        }
        size_t at=r%CAPACITY, frames=SPA_MIN(w-r,CAPACITY-at), bytes=frames*STRIDE, done=0;
        while(done<bytes) {
            ssize_t n=write(a->capture_fd,(uint8_t*)(a->samples+at*2)+done,bytes-done);
            if(n<0 && errno==EINTR) continue;
            if(n<=0) { atomic_store(&a->error,1); wake_main(a); return NULL; }
            done+=(size_t)n;
        }
        atomic_store_explicit(&a->read,r+frames,memory_order_release);
    }
    return NULL;
}
static void process(void *arg) {
    struct audio *a=arg;
    struct pw_buffer *b=pw_stream_dequeue_buffer(a->stream);
    if(!b) return;
    struct spa_data *d=&b->buffer->datas[0];
    if(!d->data) { pw_stream_queue_buffer(a->stream,b); return; }
    if(a->capture_fd>=0 || atomic_load(&a->active)) {
        struct timespec now;clock_gettime(CLOCK_MONOTONIC,&now);
        uint64_t ns=(uint64_t)now.tv_sec*1000000000+now.tv_nsec;
        if(a->last_callback_ns && ns-a->last_callback_ns>a->max_callback_gap_ns)
            a->max_callback_gap_ns=ns-a->last_callback_ns;
        a->last_callback_ns=ns;
    }
    if(a->capture_fd>=0) {
        uint64_t w=atomic_load_explicit(&a->written,memory_order_relaxed);
        uint64_t r=atomic_load_explicit(&a->read,memory_order_acquire);
        size_t frames=SPA_MIN(d->chunk->size,d->maxsize)/STRIDE;
        size_t take=SPA_MIN(frames,CAPACITY-(w-r)), at=w%CAPACITY;
        size_t offset=d->maxsize?d->chunk->offset%d->maxsize:0;
        const uint8_t *src=(uint8_t*)d->data+offset;
        /* Raw PipeWire buffers are contiguous; reject a malformed wrapped chunk. */
        if(offset+take*STRIDE>d->maxsize) take=0;
        size_t first=SPA_MIN(take,CAPACITY-at);
        memcpy(a->samples+at*2,src,first*STRIDE);
        if(take>first) memcpy(a->samples,src+first*STRIDE,(take-first)*STRIDE);
        atomic_store_explicit(&a->written,w+take,memory_order_release);
        if(take<frames) { atomic_fetch_add(&a->underrun_frames,frames-take); atomic_fetch_add(&a->underrun_events,1); }
        pw_stream_queue_buffer(a->stream,b);return;
    }
    size_t frames=d->maxsize/STRIDE;
    if(b->requested) frames=SPA_MIN(frames,b->requested);
    if(!atomic_load(&a->active)) {
        memset(d->data,0,frames*STRIDE);
        d->chunk->offset=0; d->chunk->stride=STRIDE; d->chunk->size=frames*STRIDE;
        pw_stream_queue_buffer(a->stream,b); return;
    }
    uint64_t r=atomic_load_explicit(&a->read,memory_order_relaxed);
    uint64_t w=atomic_load_explicit(&a->written,memory_order_acquire);
    size_t take=SPA_MIN(frames,w-r), at=r%CAPACITY;
    size_t first=SPA_MIN(take,CAPACITY-at);
    memcpy(d->data,a->samples+at*2,first*STRIDE);
    if(take>first) memcpy((uint8_t*)d->data+first*STRIDE,a->samples,(take-first)*STRIDE);
    if(take<frames) {
        memset((uint8_t*)d->data+take*STRIDE,0,(frames-take)*STRIDE);
        if(!atomic_load_explicit(&a->eof,memory_order_acquire)) {
            atomic_fetch_add(&a->underrun_frames,frames-take);
            atomic_fetch_add(&a->underrun_events,1);
        }
    }
    atomic_store_explicit(&a->read,r+take,memory_order_release);
    d->chunk->offset=0; d->chunk->stride=STRIDE; d->chunk->size=frames*STRIDE;
    pw_stream_queue_buffer(a->stream,b);
    if(atomic_load(&a->eof) && r+take==w) wake_main(a);
}
static void drained(void *arg) { struct audio *a=arg; pw_main_loop_quit(a->loop); }
static void state_changed(void *arg,enum pw_stream_state old,enum pw_stream_state state,const char *error) {
    (void)old; struct audio *a=arg;
    if(state==PW_STREAM_STATE_ERROR) {
        fprintf(stderr,"PipeWire PCM stream: %s\n",error?error:"unknown error");
        atomic_store(&a->error,1); pw_main_loop_quit(a->loop);
    }
}
static void wake(void *arg,uint64_t count) {
    (void)count; struct audio *a=arg;
    if(atomic_load(&a->error)) { pw_main_loop_quit(a->loop); return; }
    if(a->capture_fd>=0) return;
    uint64_t available=atomic_load(&a->written)-atomic_load(&a->read);
    if(!atomic_load(&a->active) && (available>=PREFILL || atomic_load(&a->eof))) {
        atomic_store(&a->active,true);
    }
    if(atomic_load(&a->eof) && !available && !a->flushing) {
        a->flushing=true; pw_stream_flush(a->stream,true);
    }
}
static void stop(void *arg,int sig) {
    (void)sig; struct audio *a=arg;
    atomic_store(&a->stopping,true); pw_main_loop_quit(a->loop);
}
int main(int argc,char **argv) {
    struct audio *a=calloc(1,sizeof(*a)); if(!a) return 1;
    a->ready_fd=-1;
    a->capture_fd=-1;
    if(argc==3 && !strcmp(argv[1],"--ready-fd")) a->ready_fd=atoi(argv[2]);
    if(argc==3 && !strcmp(argv[1],"--capture-file")) {
        a->capture_fd=open(argv[2],O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC,0600);
        if(a->capture_fd<0) return 1;
    }
    if(!atomic_is_lock_free(&a->read) || !atomic_is_lock_free(&a->written)) return 1;
    pw_init(&argc,&argv); a->loop=pw_main_loop_new(NULL); if(!a->loop) return 1;
    struct pw_loop *loop=pw_main_loop_get_loop(a->loop);
    a->wake=pw_loop_add_event(loop,wake,a);
    pw_loop_add_signal(loop,SIGINT,stop,a); pw_loop_add_signal(loop,SIGTERM,stop,a);
    static const struct pw_stream_events events={PW_VERSION_STREAM_EVENTS,
        .state_changed=state_changed,.process=process,.drained=drained};
    a->stream=pw_stream_new_simple(loop,"HLauncher buffered PCM",pw_properties_new(
        PW_KEY_NODE_NAME,a->capture_fd<0?"hlauncher_input":"hlauncher_record",PW_KEY_MEDIA_TYPE,"Audio",
        PW_KEY_MEDIA_CATEGORY,a->capture_fd<0?"Playback":"Capture",PW_KEY_MEDIA_ROLE,"Music",
        PW_KEY_NODE_LATENCY,"3840/48000",PW_KEY_NODE_RATE,"1/48000",
        "node.autoconnect","false",NULL),&events,a);
    if(!a->stream) return 1;
    uint8_t storage[1024]; struct spa_pod_builder builder=SPA_POD_BUILDER_INIT(storage,sizeof(storage));
    struct spa_audio_info_raw format=SPA_AUDIO_INFO_RAW_INIT(.format=SPA_AUDIO_FORMAT_F32_LE,
        .rate=RATE,.channels=2,.position={SPA_AUDIO_CHANNEL_FL,SPA_AUDIO_CHANNEL_FR});
    const struct spa_pod *params[]={spa_format_audio_raw_build(&builder,SPA_PARAM_EnumFormat,&format)};
    if(pw_stream_connect(a->stream,a->capture_fd<0?PW_DIRECTION_OUTPUT:PW_DIRECTION_INPUT,PW_ID_ANY,
        PW_STREAM_FLAG_MAP_BUFFERS|PW_STREAM_FLAG_RT_PROCESS,params,1)<0) return 1;
    pthread_t producer;
    if(pthread_create(&producer,NULL,a->capture_fd<0?produce:capture_write,a)) return 1;
    pw_main_loop_run(a->loop);
    pw_stream_destroy(a->stream);
    atomic_store(&a->stopping,true);
    if(a->capture_fd<0) pthread_cancel(producer);
    pthread_join(producer,NULL);
    fprintf(stderr,"{\"state\":\"pipewire_pcm_stats\",\"mode\":\"%s\",\"input_frames\":%llu,\"played_frames\":%llu,\"underrun_frames\":%llu,\"underrun_events\":%llu,\"max_callback_gap_ms\":%.3f}\n",
        a->capture_fd<0?"playback":"capture",
        (unsigned long long)atomic_load(&a->written),(unsigned long long)atomic_load(&a->read),
        (unsigned long long)atomic_load(&a->underrun_frames),(unsigned long long)atomic_load(&a->underrun_events),
        a->max_callback_gap_ns/1000000.0);
    if(a->capture_fd>=0) close(a->capture_fd);
    pw_main_loop_destroy(a->loop); pw_deinit(); int result=atomic_load(&a->error); free(a); return result;
}
