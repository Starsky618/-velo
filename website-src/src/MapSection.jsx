import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {ArrowsOut,ArrowsIn,ArrowUpRight,ArrowLeft,MagnifyingGlass,ArrowCounterClockwise,X} from '@phosphor-icons/react';
import {RouteThumb} from './RouteThumb';
import {MapCanvas} from './MapCanvas';
export {MapCanvas} from './MapCanvas';
const displayName=s=>s.displayName||s.name;
export function MapSection({request,onReady}) {
 const root=useRef(null),expandButton=useRef(null);
 const [enabled,setEnabled]=useState(false),[catalog,setCatalog]=useState(null),[error,setError]=useState(false),[retry,setRetry]=useState(0);
 const [selectedId,setSelectedId]=useState(null),[focusNonce,setFocusNonce]=useState(0),[query,setQuery]=useState(''),[view,setView]=useState('featured'),[expanded,setExpanded]=useState(false);
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setEnabled(true);observer.disconnect()}},{rootMargin:'450px'});observer.observe(root.current);return()=>observer.disconnect()},[]);
 useEffect(()=>{if(request?.id){setEnabled(true);setSelectedId(request.id);setFocusNonce(n=>n+1);setQuery('')}},[request]);
 useEffect(()=>{if(!enabled)return;const abort=new AbortController();setError(false);fetch('/data/segments.json').then(r=>{if(!r.ok)throw Error('catalog');return r.json()}).then(data=>{if(!abort.signal.aborted)setCatalog(data)}).catch(()=>{if(!abort.signal.aborted)setError(true)});return()=>abort.abort()},[enabled,retry]);
 useEffect(()=>{if(!expanded)return;const old=document.body.style.overflow;document.body.style.overflow='hidden';const escape=e=>{if(e.key==='Escape'){setExpanded(false);expandButton.current?.focus()}};window.addEventListener('keydown',escape);return()=>{document.body.style.overflow=old;window.removeEventListener('keydown',escape)}},[expanded]);
 useEffect(()=>{if(catalog)onReady?.()},[catalog,onReady]);
 const select=useCallback(id=>{setSelectedId(id);setFocusNonce(n=>n+1);const panel=root.current?.querySelector('.atlas-workspace');if(window.innerWidth<=760&&panel?.getBoundingClientRect().top < -70)panel.scrollIntoView({behavior:'smooth',block:'start'})},[]);
 function trapFocus(event){if(!expanded||event.key!=='Tab')return;const items=[...event.currentTarget.querySelectorAll('button,a,input,[tabindex="0"]')].filter(el=>el.offsetParent!==null);const first=items[0],last=items.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}
 const selected=catalog?.segments.find(s=>s.id===selectedId);
 const featured=useMemo(()=>catalog?catalog.featuredIds.map(id=>catalog.segments.find(s=>s.id===id)).filter(Boolean):[],[catalog]);
 const representatives=useMemo(()=>catalog?.segments.filter(s=>catalog.display.representativeIds.includes(s.id))||[],[catalog]);
 const mapSegments=useMemo(()=>{if(!selected)return representatives;return [...representatives.filter(s=>s.id!==selected.id&&s.id!==catalog.display.hiddenBy[selected.id]),selected]},[representatives,selected,catalog]);
 const results=useMemo(()=>{const q=query.trim().toLocaleLowerCase();return q?catalog?.segments.filter(s=>`${s.name} ${s.displayName||''} ${s.id}`.toLocaleLowerCase().includes(q))||[]:view==='featured'?featured:representatives},[catalog,query,view,featured,representatives]);
 return <section className="atlas-section" id="routes" ref={root} aria-labelledby="atlas-title">
  <div className="atlas-heading"><div><p className="eyebrow">VELO · 本地骑行地图</p><h2 id="atlas-title">一城好路</h2><p>看清走向，再选下一程。</p></div><div className="atlas-scope">太原及周边<br/><span>{catalog?`${representatives.length} 条代表赛段`:'本地路线档案'}</span><small>重叠已归并</small></div></div>
  {!catalog?<div className="map-loading" role="status">{error?<><p>地图资料暂未载入。</p><button onClick={()=>setRetry(n=>n+1)}>重新载入</button></>:<p>地图徐徐展开</p>}</div>:<>
   <div className={`atlas-workspace ${expanded?'atlas-expanded':''}`} role={expanded?'dialog':undefined} aria-modal={expanded||undefined} aria-label={expanded?'展开的骑行地图':undefined} onKeyDown={trapFocus}>
    <div className="atlas-toolbar"><span>TAIYUAN <span className="toolbar-divider">/</span> 骑行地图</span><div><button onClick={()=>{select(null);setQuery('')}}><ArrowCounterClockwise size={16}/>全城总览</button><button ref={expandButton} aria-label={expanded?'收起地图':'展开地图'} onClick={()=>setExpanded(v=>!v)}>{expanded?<ArrowsIn size={17}/>:<ArrowsOut size={17}/>}</button></div></div>
    <aside className="segment-sidebar" aria-label="赛段选择与详情">
     <div className="segment-search"><MagnifyingGlass size={18}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索地点或路线" aria-label="搜索 Strava 赛段"/>{query&&<button aria-label="清空赛段搜索" onClick={()=>setQuery('')}><X size={16}/></button>}</div>
     {selected?<div className="selected-segment" aria-live="polite"><button className="back-overview" onClick={()=>select(null)}><ArrowLeft size={15}/>返回路线总览</button><p className="eyebrow">{selected.kind||'本地赛段'}</p><h3>{displayName(selected)}</h3><p className="segment-description">{selected.description}</p><div className="segment-numbers"><div><strong>{(selected.distanceM/1000).toFixed(2)}</strong><span>公里</span></div>{selected.climbM!=null&&<div><strong>{Math.round(selected.climbM)}</strong><span>米爬升</span></div>}</div><p className="original-segment-name">来源赛段 · {selected.name}</p><a className="segment-source" href={selected.sourceUrl} target="_blank" rel="noreferrer">查看 Strava 原赛段<ArrowUpRight size={14}/></a></div>:<div className="map-list-intro"><h3>下一程，去哪里？</h3><p>选一个熟悉的名字，看看路的全貌。</p></div>}
     <div className="map-list-tabs" aria-label="路线列表范围"><button aria-pressed={view==='featured'} onClick={()=>setView('featured')}>热门路线</button><button aria-pressed={view==='all'} onClick={()=>setView('all')}>全部代表赛段</button><span aria-live="polite">{results.length}</span></div>
     <div className="segment-list" aria-label="Strava 赛段列表">{results.map(segment=><button key={segment.id} className={segment.id===selectedId?'selected':''} aria-pressed={segment.id===selectedId} onClick={()=>select(segment.id)} aria-label={`查看赛段：${displayName(segment)}`}><RouteThumb segment={segment}/><span><strong>{displayName(segment)}</strong><small>{(segment.distanceM/1000).toFixed(2)} 公里{segment.climbM!=null?` · ${Math.round(segment.climbM)} 米爬升`:''}</small></span><ArrowUpRight size={14}/></button>)}{!results.length&&<p className="empty-search">没有找到这个名字，换个词试试。</p>}</div>
     <p className="map-sidebar-note">{query?'搜索包含被归并的原始赛段。':'相近轨迹保留覆盖更完整的长赛段。'}</p>
    </aside>
    <MapCanvas segments={mapSegments} selectedId={selectedId} focusNonce={focusNonce} onSelect={select}/>
   </div>
   <div className="atlas-caption"><p>点选路线查看详情；地图支持双指移动与缩放。</p><details><summary>赛段与数据来源</summary><p>保留 {catalog.segments.length} 条完整 Strava 来源记录。总览按真实轨迹长度排序，短赛段有至少 90% 的长度落在更长赛段 35 米范围内时归并显示；这只是视觉去重，不合并骑行方向或成绩。搜索可查原始记录。爬升仅显示匹配该来源几何的 GLO-30 结果。</p></details></div>
   <div className="signature-heading"><p className="eyebrow">从一条熟悉的路开始</p><h3>骑友常提起的名字</h3></div>
   <div className="signature-routes">{featured.map(segment=><button className={segment.id===selectedId?'selected':''} key={segment.id} aria-label={`在地图聚焦${displayName(segment)}`} onClick={()=>{select(segment.id);root.current.scrollIntoView({behavior:'smooth',block:'start'})}}><RouteThumb segment={segment}/><div><h4>{displayName(segment)}</h4><p>{segment.description}</p><span>{(segment.distanceM/1000).toFixed(2)} 公里{segment.climbM!=null?` · 爬升 ${Math.round(segment.climbM)} 米`:''}</span></div><ArrowUpRight className="signature-arrow" size={19}/></button>)}</div>
  </>}
 </section>;
}
