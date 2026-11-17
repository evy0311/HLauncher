"""Large radio settings rows with clipped hit regions and drag/thumb scrolling."""
from dataclasses import dataclass
from PIL import ImageDraw
from .chrome import scale_bounds


@dataclass
class Row:
    title: str
    action: object
    value: str=''
    toggle: object=None


def move(ui,delta):
    view=ui.scroll_view
    ui.list_offsets[view['key']]=max(0,min(view['maximum'],view['offset']+delta))
    ui.press=ui.pressed_box=None
    ui.draw()


def viewport(ui, top, bottom, content, key):
    if not hasattr(ui,'list_offsets'):ui.list_offsets={}
    maximum=max(0,content-(bottom-top))
    offset=max(0,min(maximum,ui.list_offsets.get(key,0)));ui.list_offsets[key]=offset
    right=636 if maximum else 696
    return dict(key=key,offset=offset,maximum=maximum,bounds=(24,top,right,bottom))


def draw(ui,page,rows, *, top=128,bottom=448,key=None,height=56,step=64,size=32):
    rows=list(rows)
    view=viewport(ui,top,bottom,len(rows)*step-(step-height),key or ui.mode)
    offset=view['offset']
    _,_,right,_=view['bounds']
    base=page.image;layer=base.copy();page.image=layer;page.draw=ImageDraw.Draw(layer)
    first=len(page.actions);visible_bounds=scale_bounds(view['bounds'],page.size)
    for i,row in enumerate(rows):
        y=round(top+i*step-offset)
        if y+height<=top or y>=bottom:continue
        page.bar((24,y,right,y+height),row.title,row.action,value=row.value,toggle=row.toggle,size=size)
    visible=[]
    for (x,y,r,b),action in page.actions[first:]:
        box=(max(x,visible_bounds[0]),max(y,visible_bounds[1]),min(r,visible_bounds[2]),min(b,visible_bounds[3]))
        if box[2]>box[0] and box[3]-box[1]>=8:visible.append((box,action))
    page.actions=page.actions[:first]+visible
    base.paste(layer.crop((24,top,right,bottom)),(24,top));page.image=base;page.draw=ImageDraw.Draw(base)
    scrollbar(ui,page,view,step)


def scrollbar(ui,page,view,step, *, draggable=True):
    _,top,_,bottom=view['bounds']
    offset,maximum=view['offset'],view['maximum']
    if maximum:
        track_top=top+2;track_bottom=bottom-2;track_height=track_bottom-track_top
        content=maximum+bottom-top
        thumb_height=max(32,round(track_height*(bottom-top)/content))
        thumb_top=track_top+round((track_height-thumb_height)*offset/maximum)
        if draggable:
            view.update(track=(646,track_top,662,track_bottom),thumb_height=thumb_height,thumb_top=thumb_top)
        else:
            view['max_drag']=bottom-top-24
        page.draw.rounded_rectangle((650,track_top,658,track_bottom),radius=4,fill=page.colors.get('panel','#201a22'),outline=page.edge)
        page.draw.rounded_rectangle((651,thumb_top,657,thumb_top+thumb_height),radius=3,
                                    fill=page.accent)
        for y,direction in ((top,-1),(bottom-48,1)):
            box=(664,y,696,y+48);actual=scale_bounds(box,page.size)
            if page.pressed==actual:page.draw.rectangle(box,fill=page.colors.get('panel','#30232d'))
            color = (page.colors.get('text', '#e7dce4') if (offset > 0 if direction < 0 else offset < maximum)
                     else page.edge)
            for shift in (-5,4):
                cy=y+24+shift
                page.draw.line([(669,cy-direction*4),(680,cy+direction*4),(691,cy-direction*4)],fill=color,width=3)
            page.actions.append((actual,lambda direction=direction:move(ui,direction*step)))
    ui.scroll_view=view


def touch(ui,action,point):
    view=getattr(ui,'scroll_view',None);gesture=getattr(ui,'list_drag',None)
    if not view or not view['maximum']:
        ui.list_drag=None;return False
    if gesture and gesture['key']!=view['key']:gesture=ui.list_drag=None
    if not point:return False
    x,y=point[0]*720/ui.fb.w,point[1]*480/ui.fb.h
    if action=='down':
        track=view.get('track')
        if track and track[0]<=x<=track[2] and track[1]<=y<=track[3]:
            anchor=y-view['thumb_top'] if view['thumb_top']<=y<=view['thumb_top']+view['thumb_height'] else view['thumb_height']/2
            gesture=ui.list_drag=dict(key=view['key'],kind='thumb',anchor=anchor,moved=True)
        elif view['bounds'][0]<=x<=view['bounds'][2] and view['bounds'][1]<=y<=view['bounds'][3]:
            ui.list_drag=dict(key=view['key'],kind='content',x=x,y=y,offset=view['offset'],moved=False)
            return False
        else:return False
    if not gesture:return False
    if gesture['kind']=='content':
        if action=='move' and abs(y-gesture['y'])>8:gesture['moved']=True
        delta=y-gesture['y']
        if limit := view.get('max_drag'):
            delta=max(-limit,min(limit,delta))
        offset=gesture['offset']-delta
    else:
        track=view['track'];travel=max(1,track[3]-track[1]-view['thumb_height'])
        offset=(y-track[1]-gesture['anchor'])/travel*view['maximum']
    if gesture['moved']:
        ui.list_offsets[view['key']]=max(0,min(view['maximum'],offset))
        ui.press=ui.pressed_box=None
        if action in ('up','unused'):ui.list_drag=None
        ui.draw();return True
    if action in ('up','unused'):ui.list_drag=None
    return False
