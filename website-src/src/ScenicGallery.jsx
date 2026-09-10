import {useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,ArrowsOutSimple,MapTrifold} from '@phosphor-icons/react';
import {scenes} from './scenes';
export function SceneImage({scene,className='',loading='lazy'}) {
  return <div className={`scene-picture ${scene.crop?'skyline-crop':''} ${className}`}>
    <img src={scene.image} alt={scene.name} loading={loading} style={{objectPosition:scene.position||'center top'}} />
  </div>;
}
export function ScenicGallery({onOpen,onMap}) {
  const [index,setIndex]=useState(0);
  const strip=useRef(null);
  const scene=scenes[index];
  function choose(next) {
    const actual=(next+scenes.length)%scenes.length;
    setIndex(actual);
    const rail=strip.current,thumb=rail?.children[actual];
    if(rail&&thumb){const r=rail.getBoundingClientRect(),t=thumb.getBoundingClientRect();if(t.left<r.left)rail.scrollBy({left:t.left-r.left,behavior:'smooth'});else if(t.right>r.right)rail.scrollBy({left:t.right-r.right,behavior:'smooth'});}
  }
  return <section className="scenic-section" id="scenery" aria-labelledby="scenic-title">
    <div className="scenic-heading"><div><p className="eyebrow">山河 · 城市 · 人间</p><h2 id="scenic-title">太原风景线</h2></div><p>从一场日落，到一城初醒。</p></div>
    <div className="scenic-stage">
      <button className="scenic-photo-button" onClick={()=>onOpen(scene)} aria-label={`放大查看${scene.name}`}><SceneImage scene={scene} loading="eager" /><span className="expand-photo"><ArrowsOutSimple size={20}/></span></button>
      <div className="scenic-caption"><div className="scene-count"><span>{String(index+1).padStart(2,'0')}</span><span> / {String(scenes.length).padStart(2,'0')}</span></div><div className="scenic-title-block" aria-live="polite"><p className="scene-place">{scene.place} · {scene.theme}</p><h3>{scene.name}</h3><p>{scene.description}</p></div><div className="scenic-actions">
        {scene.segmentId?<button className="text-link" onClick={()=>onMap(scene.segmentId)}><MapTrifold size={18}/>看相关赛段</button>:<a className="text-link" href="#routes"><MapTrifold size={18}/>地图总览</a>}
        <div className="gallery-arrows"><button onClick={()=>choose(index-1)} aria-label="上一幅风景"><ArrowLeft size={20}/></button><button onClick={()=>choose(index+1)} aria-label="下一幅风景"><ArrowRight size={20}/></button></div>
      </div></div>
    </div>
    <div className="scene-thumbnails" ref={strip} aria-label="选择风景照片">{scenes.map((item,i)=><button key={item.id} aria-label={`选择照片：${item.name}`} aria-pressed={i===index} onClick={()=>choose(i)}><SceneImage scene={item}/><span>{String(i+1).padStart(2,'0')} · {item.name}</span></button>)}</div>
  </section>;
}
