import {useEffect,useRef,useState} from 'react';
import 'maplibre-gl/dist/maplibre-gl.css';
import {ArrowsOut,Minus,Plus,ArrowCounterClockwise} from '@phosphor-icons/react';
const EMPTY={type:'FeatureCollection',features:[]};
const collection=features=>({type:'FeatureCollection',features});
const lineFeature=(coordinates,properties={})=>({type:'Feature',properties,geometry:{type:'LineString',coordinates}});
const pointFeature=(coordinates,properties={})=>({type:'Feature',properties,geometry:{type:'Point',coordinates}});
function boundsOf(segments){let west=180,south=90,east=-180,north=-90;for(const s of segments)for(const [x,y] of s.coordinates){west=Math.min(west,x);east=Math.max(east,x);south=Math.min(south,y);north=Math.max(north,y)}return west<east?[[west,south],[east,north]]:[[112.2,37.65],[112.7,38.02]]}
export function MapCanvas({segments,selectedId,focusNonce=0,onSelect=()=>{},ariaLabel='太原及周边路线地图',trip=null,compact=false,drawMode=false,drawnCoordinates=null,onDraw=null,onReadyChange=null}) {
 const container=useRef(null),instance=useRef(null),latest=useRef({}),update=useRef(()=>{}),[ready,setReady]=useState(false),[error,setError]=useState(false),[retry,setRetry]=useState(0),[enabled,setEnabled]=useState(false);
 latest.current={segments,selectedId,focusNonce,onSelect,trip,onDraw,onReadyChange,drawnCoordinates};
 const stroke=useRef(null);
 function paintSketch(points){const map=instance.current;map?.getSource('sketch')?.setData(points?.length>1?collection([lineFeature(points)]):EMPTY);map?.getSource('sketch-ends')?.setData(points?.length>1?collection([pointFeature(points[0],{label:'起点'}),pointFeature(points.at(-1),{label:'终点'})]):EMPTY)}
 function position(event){const rect=container.current.getBoundingClientRect();const p=instance.current.unproject([Math.max(0,Math.min(rect.width,event.clientX-rect.left)),Math.max(0,Math.min(rect.height,event.clientY-rect.top))]);return [p.lng,p.lat]}
 function beginStroke(event){if(!ready||event.button!==0||stroke.current)return;event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);stroke.current={id:event.pointerId,points:[position(event)],x:event.clientX,y:event.clientY};paintSketch([])}
 function moveStroke(event){const v=stroke.current;if(!v||v.id!==event.pointerId||Math.hypot(event.clientX-v.x,event.clientY-v.y)<2)return;v.points.push(position(event));v.x=event.clientX;v.y=event.clientY;paintSketch(v.points)}
 function endStroke(event){const v=stroke.current;if(!v||v.id!==event.pointerId)return;v.points.push(position(event));stroke.current=null;event.currentTarget.releasePointerCapture(event.pointerId);if(v.points.length>1){paintSketch(v.points);latest.current.onDraw?.(v.points)}}
 function cancelStroke(){stroke.current=null;paintSketch(drawnCoordinates)}
 const fit=(animate=true)=>{const m=instance.current;if(!m)return;const v=latest.current;const chosen=v.segments.find(s=>s.id===v.selectedId);const lines=v.drawnCoordinates?.length>1?[{coordinates:v.drawnCoordinates}]:v.trip?[v.trip]:chosen?[chosen]:v.segments;m.fitBounds(boundsOf(lines),{padding:compact?38:{top:70,bottom:70,left:55,right:55},maxZoom:chosen?14:11.5,duration:animate&&!matchMedia('(prefers-reduced-motion: reduce)').matches?600:0})};
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setEnabled(true);observer.disconnect()}},{rootMargin:'350px'});observer.observe(container.current);return()=>observer.disconnect()},[]);
 useEffect(()=>{
  if(!enabled)return;
  let disposed=false,map,observer;setReady(false);setError(false);latest.current.onReadyChange?.(false);
  import('maplibre-gl').then(({default:maplibregl})=>{
   if(disposed)return;
   map=new maplibregl.Map({container:container.current,style:'/data/map-style.json',center:[112.45,37.85],zoom:10,minZoom:7,maxZoom:17,attributionControl:{compact:true},dragRotate:false,pitchWithRotate:false,touchPitch:false,cooperativeGestures:true,locale:{'CooperativeGesturesHandler.WindowsHelpText':'按住 Ctrl 滚动缩放地图','CooperativeGesturesHandler.MacHelpText':'按住 ⌘ 滚动缩放地图','CooperativeGesturesHandler.MobileHelpText':'使用双指移动地图'}});
   instance.current=map;map.touchZoomRotate.disableRotation();map.addControl(new maplibregl.ScaleControl({maxWidth:80,unit:'metric'}),'bottom-left');
   map.on('error',()=>{if(!disposed)setError(true)});
   map.on('load',()=>{
    if(disposed)return;
    for(const id of ['routes','active','climb','points','names','sketch','sketch-ends'])map.addSource(id,{type:'geojson',data:EMPTY});
    map.addLayer({id:'route-halo',type:'line',source:'routes',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#ffffff','line-width':5,'line-opacity':.75}});
    map.addLayer({id:'route-lines',type:'line',source:'routes',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#718995','line-width':2.6,'line-opacity':.85}});
    map.addLayer({id:'route-hit',type:'line',source:'routes',paint:{'line-width':16,'line-opacity':0}});
    map.addLayer({id:'active-halo',type:'line',source:'active',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#ffffff','line-width':11}});
    map.addLayer({id:'active-line',type:'line',source:'active',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#087cf0','line-width':6}});
    map.addLayer({id:'climb-line',type:'line',source:'climb',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#e47833','line-width':6}});
    map.addLayer({id:'point-circles',type:'circle',source:'points',paint:{'circle-radius':7,'circle-color':'#ffffff','circle-stroke-width':3,'circle-stroke-color':'#087cf0'}});
    map.addLayer({id:'point-labels',type:'symbol',source:'points',layout:{'text-field':['get','label'],'text-font':['Noto Sans Regular'],'text-size':12,'text-offset':[0,1.8],'text-anchor':'top','text-allow-overlap':false},paint:{'text-color':'#20262c','text-halo-color':'#ffffff','text-halo-width':3}});
    map.addLayer({id:'route-names',type:'symbol',source:'names',layout:{'text-field':['get','name'],'text-font':['Noto Sans Regular'],'text-size':12,'text-padding':20,'text-optional':true},paint:{'text-color':'#344b59','text-halo-color':'#ffffff','text-halo-width':3}});
    map.addLayer({id:'sketch-halo',type:'line',source:'sketch',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#fff','line-width':10}});
    map.addLayer({id:'sketch-line',type:'line',source:'sketch',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#087cf0','line-width':5}});
    map.addLayer({id:'sketch-end-dots',type:'circle',source:'sketch-ends',paint:{'circle-radius':6,'circle-color':'#fff','circle-stroke-width':3,'circle-stroke-color':'#087cf0'}});
    map.addLayer({id:'sketch-end-labels',type:'symbol',source:'sketch-ends',layout:{'text-field':['get','label'],'text-font':['Noto Sans Regular'],'text-size':12,'text-offset':[0,1.7],'text-anchor':'top'},paint:{'text-color':'#222','text-halo-color':'#fff','text-halo-width':3}});
    map.on('click','route-hit',event=>{if(!latest.current.trip&&event.features?.[0])latest.current.onSelect(event.features[0].properties.id)});
    map.on('click','route-names',event=>{if(event.features?.[0])latest.current.onSelect(event.features[0].properties.id)});
    map.on('mouseenter','route-hit',()=>{map.getCanvas().style.cursor='pointer'});map.on('mouseleave','route-hit',()=>{map.getCanvas().style.cursor=''});
    update.current=()=>{
     const v=latest.current,selected=v.segments.find(s=>s.id===v.selectedId),active=v.trip||selected;
     map.getSource('routes').setData(collection(v.trip?[]:v.segments.filter(s=>s.id!==v.selectedId).map(s=>lineFeature(s.coordinates,{id:s.id}))));
     map.getSource('active').setData(active?collection([lineFeature(active.coordinates)]):EMPTY);
     map.getSource('climb').setData(v.trip?collection([lineFeature(v.trip.climbCoordinates)]):EMPTY);
     const pts=v.trip?v.trip.waypoints.map(p=>pointFeature(p.coordinates,{label:`${p.name==='出发 / 返回'?'起终点 · ':p.name==='折返点'?'折返 · ':''}${p.label}`})):selected?[pointFeature(selected.coordinates[0],{label:'起点'}),pointFeature(selected.coordinates.at(-1),{label:'终点'})]:[];
     map.getSource('points').setData(collection(pts));
     map.getSource('names').setData(collection(active?[]:v.segments.filter(s=>s.displayName).map(s=>pointFeature(s.coordinates[Math.floor(s.coordinates.length*.55)],{id:s.id,name:s.displayName}))));
     map.setPaintProperty('route-lines','line-opacity',active?.28:.85);map.setPaintProperty('route-lines','line-width',active?1.8:2.6);
    };
    update.current();fit(false);setReady(true);latest.current.onReadyChange?.(true);
   });
   observer=new ResizeObserver(()=>{map.resize();fit(false)});observer.observe(container.current);
  }).catch(()=>{if(!disposed)setError(true)});
  return()=>{disposed=true;observer?.disconnect();update.current=()=>{};map?.remove();instance.current=null};
 },[retry,enabled]);
 useEffect(()=>{if(ready){update.current();fit()}},[segments,selectedId,focusNonce,trip,ready]);
 useEffect(()=>{if(ready&&!stroke.current)paintSketch(drawnCoordinates)},[drawnCoordinates,ready]);
 useEffect(()=>{if(!drawMode)cancelStroke()},[drawMode]);
 return <div className={`map-pane ${compact?'compact-map':''}`}>
  <div ref={container} className="city-map" role="region" aria-label={ariaLabel}/>
  {!ready&&!error&&<span className="map-load-label" role="status">正在展开地图…</span>}
  {drawMode&&<div className="sketch-input" role="application" aria-label="手绘路线画布" onPointerDown={beginStroke} onPointerMove={moveStroke} onPointerUp={endStroke} onPointerCancel={cancelStroke}/>}
  {!drawMode&&<div className="map-tools"><button aria-label="地图放大" onClick={()=>instance.current?.zoomIn()}><Plus size={18}/></button><button aria-label="地图缩小" onClick={()=>instance.current?.zoomOut()}><Minus size={18}/></button><button aria-label="重新聚焦路线" onClick={()=>fit()}><ArrowsOut size={18}/></button></div>}
  {!compact&&<div className="map-legend"><span className="legend-stroke active"/>{trip?'完整行程':'选中路线'}<span className={`legend-stroke ${trip?'climb':''}`}/>{trip?'途经爬坡':'代表赛段'}</div>}
  {error&&<div className="map-message" role="status">部分地图资料未加载。<button onClick={()=>setRetry(n=>n+1)}><ArrowCounterClockwise size={14}/>重新载入</button></div>}
 </div>;
}
