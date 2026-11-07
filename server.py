import asyncio, json, math, os, random, secrets, time
from pathlib import Path
from aiohttp import web, WSMsgType
import pymunk

ROOT=Path(__file__).parent
rooms={}
COLORS=['#a6ff65','#79c9ff','#ffbc6e','#e9a0ff','#ff7b94']
class Room:
 def __init__(self,code,name="Untitled playground"):
  self.name=name; self.created=time.monotonic(); self.code=code; self.space=pymunk.Space(); self.space.gravity=(0,1100); self.players={}; self.objects={}; self.next_id=0; self.tick=0
  self.platforms=[(900,890,1800,40),(0,450,30,900),(1800,450,30,900),(360,680,300,24),(1380,680,300,24),(900,470,340,24)]
  for x,y,w,h in self.platforms:
   b=pymunk.Body(body_type=pymunk.Body.STATIC); b.position=x,y; s=pymunk.Poly.create_box(b,(w,h)); s.friction=.9; self.space.add(b,s)
  for i in range(10): self.spawn('box',750+(i%3)*55,250-(i//3)*50)
 def spawn(self,kind,x,y):
  if len(self.objects)>=120:return
  specs={'box':(44,44,3),'ball':(56,56,3),'plank':(170,18,4),'domino':(22,90,3),'heavy':(65,65,22),'wheel':(76,76,6),'triangle':(70,60,4),'bouncy':(70,70,1)}
  if kind not in specs:kind='box'
  w,h,mass=specs[kind];circle=kind in ['ball','wheel','bouncy']
  b=pymunk.Body(mass,pymunk.moment_for_circle(mass,0,w/2) if circle else pymunk.moment_for_box(mass,(w,h)));b.position=x,y
  if circle:s=pymunk.Circle(b,w/2)
  elif kind=='triangle':s=pymunk.Poly(b,[(-w/2,h/2),(0,-h/2),(w/2,h/2)])
  else:s=pymunk.Poly.create_box(b,(w,h))
  s.friction=.85;s.elasticity=.95 if kind=='bouncy' else (.6 if circle else .15)
  self.space.add(b,s);self.next_id+=1;self.objects[self.next_id]=(b,s,kind,random.choice(COLORS))
 def pick(self,x,y):
  return next(((k,o) for k,o in reversed(list(self.objects.items())) if o[1].point_query((x,y)).distance<8),None)
 def remove(self,k):
  b,s,*_=self.objects[k]
  for p in self.players.values():
   if p['joint'] is not None and p['joint'].b==b:self.release(p)
  self.space.remove(s,b);del self.objects[k]
 def release(self,p):
  if p['joint'] is not None:self.space.remove(p['joint']); p['joint']=None
 def state(self):
  return {'type':'state','gravity':self.space.gravity.y,'players':[{'id':k,'name':p['name'],'x':p['body'].position.x,'y':p['body'].position.y,'color':p['color']} for k,p in self.players.items()], 'objects':[{'id':k,'x':b.position.x,'y':b.position.y,'a':b.angle,'kind':kind,'color':c,'frozen':b.body_type==pymunk.Body.STATIC} for k,(b,s,kind,c) in self.objects.items()]}
 def step(self):
  for p in self.players.values():
   b=p['body']; keys=p['keys']; target=(int('d' in keys or 'ArrowRight' in keys)-int('a' in keys or 'ArrowLeft' in keys))*330
   b.velocity=(b.velocity.x+(target-b.velocity.x)*.22,b.velocity.y)
   grounded=any(self.space.point_query((b.position.x+dx,b.position.y+28),5,pymunk.ShapeFilter(mask=0xffffffff ^ 2)) for dx in [-12,12])
   if (' ' in keys or 'w' in keys or 'ArrowUp' in keys) and grounded and p['jump']<=0:b.velocity=(b.velocity.x,-620); p['jump']=18
   p['jump']-=1
   if b.position.y>1100:b.position=(200,300);b.velocity=(0,0)
   if p['joint'] is not None:
    body=p['joint'].b; delta=pymunk.Vec2d(*p['mouse'])-body.position
    body.apply_force_at_world_point(delta*500-body.velocity*45,body.position)
  self.space.step(1/60)
async def index(req):return web.FileResponse(ROOT/'static/index.html')
async def list_rooms(req):
 return web.json_response({'rooms':[{'code':r.code,'name':r.name,'players':len(r.players),'capacity':8,'objects':len(r.objects)} for r in rooms.values()]},headers={'Cache-Control':'no-store'})
async def websocket(req):
 ws=web.WebSocketResponse(heartbeat=20,max_msg_size=4096);await ws.prepare(req); room=None;pid=secrets.token_hex(6)
 try:
  async for msg in ws:
   if msg.type!=WSMsgType.TEXT:continue
   try:d=json.loads(msg.data)
   except (ValueError,TypeError):continue
   if not isinstance(d,dict):continue
   if room is None:
    if d.get('type') not in ['join','create']:continue
    code=str(d.get('code','')).strip().upper()
    if d.get('type')=='create':
     if len(rooms)>=100:await ws.send_json({'type':'error','message':'Server full'});continue
     code=secrets.token_hex(3).upper();rooms[code]=Room(code,str(d.get('room_name','')).strip()[:40] or 'Untitled playground')
    if code not in rooms:await ws.send_json({'type':'error','message':'Room not found. Check the code.'});continue
    room=rooms[code]
    if len(room.players)>=8:room=None;await ws.send_json({'type':'error','message':'Room full (8 players)'});continue
    b=pymunk.Body(5,float('inf'));b.position=(200+len(room.players)*45,300);s=pymunk.Poly.create_box(b,(30,48));s.friction=.2;s.filter=pymunk.ShapeFilter(categories=2);room.space.add(b,s)
    room.players[pid]={'body':b,'shape':s,'ws':ws,'name':str(d.get('name','Player')).strip()[:20] or 'Player','color':COLORS[len(room.players)%5],'keys':[],'mouse':[0,0],'joint':None,'jump':0,'last':0}
    await ws.send_json({'type':'welcome','id':pid,'code':code,'platforms':room.platforms,'name':room.name});continue
   p=room.players[pid];kind=d.get('type')
   if kind=='input':
    p['keys']=[k for k in (d.get('keys',[]) if isinstance(d.get('keys'),list) else [])[:12] if k in ['a','d','w',' ','ArrowUp','ArrowLeft','ArrowRight']]
   elif kind in ['spawn','grab','mouse','blast','delete','freeze','duplicate','rotate']:
    try:x=max(40,min(1760,float(d['x'])));y=max(30,min(840,float(d['y'])))
    except (KeyError,ValueError,TypeError):continue
    if not math.isfinite(x+y):continue
    p['mouse']=[x,y]
    if kind=='mouse':continue
    if time.monotonic()-p['last']<.15:continue
    p['last']=time.monotonic()
    if kind=='spawn':room.spawn(d.get('kind') if isinstance(d.get('kind'),str) else 'box',x,y)
    if kind=='grab':
     room.release(p)
     for b,s,_,_ in reversed(list(room.objects.values())):
      if b.body_type==pymunk.Body.DYNAMIC and s.point_query((x,y)).distance<8:
       # A zero-force spring tracks the selected body; force is applied by step.
       j=pymunk.DampedSpring(room.space.static_body,b,(x,y),b.world_to_local((x,y)),0,0,0);room.space.add(j);p['joint']=j;break
    if kind in ['delete','freeze','duplicate','rotate']:
     hit=room.pick(x,y)
     if hit:
      k,(b,s,objkind,color)=hit
      if kind=='delete':room.remove(k)
      elif kind=='duplicate':room.spawn(objkind,min(1740,x+55),max(60,y-55))
      elif kind=='freeze':
       for other in room.players.values():
        if other['joint'] is not None and other['joint'].b==b:room.release(other)
       if b.body_type==pymunk.Body.STATIC:
        b.body_type=pymunk.Body.DYNAMIC;s.mass={'heavy':22,'plank':4,'triangle':4,'wheel':6,'bouncy':1}.get(objkind,3);b.activate()
       else:b.velocity=(0,0);b.angular_velocity=0;b.body_type=pymunk.Body.STATIC
       room.space.reindex_shapes_for_body(b)
      elif kind=='rotate':b.angle+=math.pi/4;room.space.reindex_shapes_for_body(b);b.activate()
    if kind=='blast':
     for b,*_ in room.objects.values():
      if b.body_type!=pymunk.Body.DYNAMIC:continue
      delta=b.position-(x,y);dist=max(delta.length,20)
      if dist<280:b.apply_impulse_at_world_point((delta.normalized() if delta.length else pymunk.Vec2d(0,-1))*(280-dist)*24,b.position)
   elif kind=='release':room.release(p)
 except (ConnectionError,asyncio.CancelledError):pass
 finally:
  if room and pid in room.players:
   p=room.players.pop(pid);room.release(p);room.space.remove(p['body'],p['shape'])
   if not room.players:rooms.pop(room.code,None)
 return ws
async def loop(app):
 async def run():
  while True:
   start=time.monotonic()
   for room in list(rooms.values()):
    room.step();room.tick+=1
    if room.tick%3==0:
     payload=json.dumps(room.state());await asyncio.gather(*(p['ws'].send_str(payload) for p in list(room.players.values()) if not p['ws'].closed),return_exceptions=True)
   await asyncio.sleep(max(0,1/60-(time.monotonic()-start)))
 task=asyncio.create_task(run());yield;task.cancel()
 try:await task
 except asyncio.CancelledError:pass
app=web.Application();app.router.add_get('/',index);app.router.add_get('/ws',websocket);app.router.add_get('/api/rooms',list_rooms);app.cleanup_ctx.append(loop)
if __name__=='__main__':web.run_app(app,host='0.0.0.0',port=int(os.environ.get('PORT',8000)))
