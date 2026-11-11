// Bound the video backlog without making the CarPlay USB callback wait.
const startCode = Buffer.from([0, 0, 1]);

export class VideoOutput {
  constructor(output, send, requestFrame) {
    this.output = output;
    this.send = send;
    this.requestFrame = requestFrame;
    this.reset();
  }

  reset() {
    this.sps = null;
    this.pps = null;
    this.resync = false;
    this.requested = false;
    this.dropped = 0;
  }

  push(data) {
    if (this.output.destroyed) return;
    let idr = false;
    for (let start = data.indexOf(startCode); start >= 0;) {
      const next = data.indexOf(startCode, start + 3);
      const kind = data[start + 3] & 31;
      if (kind === 7 || kind === 8) {
        // Copy these small NALs so a parameter set doesn't retain a whole USB frame.
        const nal = Buffer.from(data.subarray(start, next < 0 ? data.length : next));
        if (kind === 7) this.sps = nal;
        else this.pps = nal;
      }
      if (kind === 5) idr = true;
      start = next;
    }
    if (this.output.writableLength >= 256 * 1024 || data.length > 8 * 1024 * 1024) {
      this.resync = true;
      this.requested = false;
      this.dropped++;
      return;
    }
    if (!this.resync) {
      this.send(1, data);
      return;
    }
    if (!idr || !this.sps || !this.pps || this.sps.length + this.pps.length + data.length > 8 * 1024 * 1024) {
      this.dropped++;
      if (!this.requested) {
        this.requested = true;
        this.requestFrame();
      }
      return;
    }
    // Send a reset in wire order immediately before the first decodable picture.
    this.send(4, Buffer.alloc(0));
    this.send(1, Buffer.concat([this.sps, this.pps, data]));
    this.resync = this.requested = false;
  }
}
