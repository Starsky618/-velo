import {useState} from 'react';
import {ArrowRight,DownloadSimple,ArrowCounterClockwise,Check,ArrowDown} from '@phosphor-icons/react';
import {MapCanvas} from './MapCanvas';
import demoSegments from './data/demo-segments.json';
import trip from './data/day-trip.json';
import {downloadTrip} from './tripExport';
import {SketchDemo} from './SketchDemo';
const tripSegments=[];
const examples=[{id:'scenery',label:'想看风景',question:'太原哪里骑车风景好？',segmentId:'29860666'},{id:'climbing',label:'想骑一整天',question:'我 FTP 200 瓦，今天想爬坡，有没有能骑一整天的路线？'},{id:'sketch',label:'手绘一条路',question:'有想走的方向，可以直接在地图上画出来吗？'}];
export function ProductDemo({onMap,onJoin}) {
 const [index,setIndex]=useState(1),[showDetails,setShowDetails]=useState(false),[generated,setGenerated]=useState(true),[downloaded,setDownloaded]=useState('');
 const example=examples[index],segment=demoSegments.find(s=>s.id==='29860666');
 const segmentSets=useState(()=>demoSegments.reduce((result,s)=>({...result,[s.id]:[s]}),{}))[0];
 function choose(next){setIndex(next);setShowDetails(false);setGenerated(true);setDownloaded('')}
 function keyboard(event){if(event.key==='ArrowRight'||event.key==='ArrowLeft'){event.preventDefault();const next=(index+(event.key==='ArrowRight'?1:examples.length-1))%examples.length;choose(next);document.getElementById(`demo-tab-${next}`)?.focus()}}
 function save(format){downloadTrip(trip,format);setDownloaded(format==='gpx'?'GPX 已准备下载':'路书已准备下载')}
 return <section className={`product-demo ${index!==0?'is-trip':''}`} id="how-it-works" aria-labelledby="demo-title">
  <div className="demo-intro"><p className="eyebrow">从一个问题开始</p><h2 id="demo-title">今天，<br/>想怎样骑？</h2><p>想去的风景，能留出的时间。<br/>把你的想法说给 VELO。</p><div className="demo-tabs" role="tablist" aria-label="产品演示场景" onKeyDown={keyboard}>{examples.map((item,i)=><button id={`demo-tab-${i}`} key={item.id} role="tab" aria-selected={i===index} aria-controls="demo-panel" tabIndex={i===index?0:-1} onClick={()=>choose(i)}>{item.label}</button>)}</div><p className="demo-disclosure">{index===2?'在地图上，亲手画一条路。':'交互示意 · 基于真实赛段资料'}</p><button className="demo-join" onClick={onJoin}>了解社群服务<ArrowRight size={17}/></button>
   {index===1&&<div className="demo-narrative"><p>说出想法</p><ArrowDown size={15}/><p>连起出发点、爬坡与归途</p><ArrowDown size={15}/><p>带着完整路书出发</p></div>}
  </div>
  <div className="demo-board" id="demo-panel" role="tabpanel" aria-labelledby={`demo-tab-${index}`}>
   <div className="demo-question"><span>你可以这样问</span><p>{example.question}</p>{index===1&&<small className="demo-conditions"><span>示例：冶峪沟口出发</span><span>6–7 小时</span><span>原点返回</span></small>}</div>
   {index===2?<SketchDemo/>:index===1?<>
    {!generated?<div className="trip-generate"><span className="demo-velo">VELO</span><h3>把这一整天，连成一条路。</h3><p>从集合点出发，把万亩爬坡、山间起伏和归途安排在一起。</p><button onClick={()=>setGenerated(true)}>演示生成完整路线<ArrowRight size={17}/></button></div>:<>
     <div className="trip-title"><div><span className="trip-status"><Check size={14}/>完整行程 · 方案示意</span><h3>{trip.name}</h3></div><button aria-label="重新播放全天规划演示" onClick={()=>{setGenerated(false);setDownloaded('')}}><ArrowCounterClockwise size={19}/></button></div>
     <div className="trip-map"><MapCanvas segments={tripSegments} trip={trip} ariaLabel="全天完整路线：冶峪沟口，经万亩爬坡、天龙山石碑，返回冶峪沟口"/></div>
     <div className="trip-summary"><div><strong>{(trip.distanceM/1000).toFixed(1)}</strong><span>公里，全程</span></div><div><strong>6–7</strong><span>小时，含休息</span></div><div><strong>往返</strong><span>起终点已连通</span></div></div>
     <div className="trip-roadbook"><div className="trip-endpoints"><p><span>起</span>{trip.startName}</p><p><span>经</span>万亩爬坡 · 天龙山石碑折返</p><p><span>终</span>{trip.endName}</p></div><button className="demo-detail-toggle" aria-expanded={showDetails} aria-controls="trip-legs" onClick={()=>setShowDetails(v=>!v)}>{showDetails?'收起行程':'展开路书'}<ArrowDown size={15}/></button>{showDetails&&<div id="trip-legs"><ol>{trip.legs.map((leg,i)=><li key={i}><span>{(leg.fromM/1000).toFixed(1)} km</span><div><strong>{leg.name}</strong><small>这一程 {leg.distanceM<1000?`${Math.round(leg.distanceM)} 米`:`${(leg.distanceM/1000).toFixed(1)} 公里`}</small></div></li>)}</ol><p>{trip.timeBasis}</p></div>}<div className="trip-exports"><button onClick={()=>save('gpx')}><DownloadSimple size={17}/>导出 GPX</button><button onClick={()=>save('roadbook')}>保存路书<ArrowRight size={16}/></button></div><p className="trip-export-status" role="status">{downloaded||'完整轨迹可导出，行程随身带走。'}</p></div>
    </>}
   </>:<><div className="demo-route-map"><MapCanvas segments={segmentSets[segment.id]} selectedId={segment.id} focusNonce={1} onSelect={()=>onMap(segment.id)} compact ariaLabel="演示中的真实赛段地图"/></div><div className="demo-response"><div className="demo-response-title"><span className="demo-velo">VELO</span><span>示意回答</span></div><h3>可以先看看二库这一带。</h3><p>先看你想去的风景，再把位置和赛段走向放到一起。</p><div className="demo-segment-facts"><span>{segment.name}</span><span>{(segment.distanceM/1000).toFixed(2)} 公里 · 爬升 {Math.round(segment.climbM)} 米</span></div><button className="demo-detail-toggle" aria-expanded={showDetails} aria-controls="demo-detail" onClick={()=>setShowDetails(v=>!v)}>{showDetails?'收起说明':'再了解一点'}<ArrowRight size={15}/></button>{showDetails&&<p className="demo-details" id="demo-detail">阁楼、角子崖，各有不同的视野。先了解这一带，再结合出发位置安排往返。</p>}<button className="demo-map-link" onClick={()=>onMap(segment.id)}>在地图上看这条赛段<ArrowRight size={16}/></button></div></>}
  </div>
 </section>;
}
