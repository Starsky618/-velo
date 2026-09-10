import { useEffect, useRef, useState } from 'react';
import {ScenicGallery,SceneImage} from './ScenicGallery';
import {MapSection} from './MapSection';
import {ProductDemo} from './ProductDemo';
import {CommunityStats,FAQ,CommunityDialog,SiteFooter} from './Community';
import {community} from './siteContent';
import {ClubSection} from './ClubSection';
function settleLowerAnchor(){const hash=window.location.hash;if(['#community','#faq'].includes(hash))requestAnimationFrame(()=>document.getElementById(hash.slice(1))?.scrollIntoView({behavior:'instant'}))}
export function App() {
  useEffect(()=>{let active=true;document.fonts.ready.then(()=>{if(active&&window.location.hash)document.getElementById(window.location.hash.slice(1))?.scrollIntoView({behavior:'instant'})});return()=>{active=false}},[]);
  const [activePlace, setActivePlace] = useState(null);
  const [mapRequest,setMapRequest]=useState(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [joinOpen,setJoinOpen]=useState(false);
  const [menuOpen,setMenuOpen]=useState(false);
  const [scrolled,setScrolled]=useState(false);
  const menuButton=useRef(null);
  useEffect(()=>{const update=()=>setScrolled(window.scrollY>90);update();window.addEventListener('scroll',update,{passive:true});return()=>window.removeEventListener('scroll',update)},[]);
  useEffect(()=>{if(!menuOpen)return;const close=e=>{if(e.key==='Escape'){setMenuOpen(false);menuButton.current?.focus()}};window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close)},[menuOpen]);
  const dialogRef = useRef(null);
  const lastFocus = useRef(null);
  const isOpen = Boolean(activePlace || aboutOpen || joinOpen);
  useEffect(() => {
    if (!isOpen) return;
    const dialog = dialogRef.current;
    lastFocus.current = document.activeElement;
    dialog.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      lastFocus.current?.focus({preventScroll:true});
    };
  }, [isOpen]);
  useEffect(()=>{if(isOpen)dialogRef.current?.querySelector(".dialog-close")?.focus({preventScroll:true})},[activePlace,aboutOpen,joinOpen,isOpen]);
  function closeDialog() { setActivePlace(null); setAboutOpen(false); setJoinOpen(false); }
  function openJoin(){setMenuOpen(false);setActivePlace(null);setAboutOpen(false);setJoinOpen(true)}
  function openAbout(){setMenuOpen(false);setActivePlace(null);setJoinOpen(false);setAboutOpen(true)}
  function jumpToMap(id) {
    closeDialog();setMapRequest({id,nonce:Date.now()});
    requestAnimationFrame(()=>document.getElementById('routes')?.scrollIntoView({behavior:'smooth',block:'start'}));
  }
  return <>
    <a className="skip-link" href="#routes">跳至路线</a>
    <header className={`site-header ${scrolled?'is-scrolled':''}`}>
      <a className="wordmark" href="#" aria-label="VELO 首页"><span aria-hidden="true"/>VELO</a>
      <nav className="desktop-nav" aria-label="主导航"><a href="#how-it-works">如何使用</a><a href="#scenery">风景</a><a href="#routes">地图</a><a href="#community">社群</a><button onClick={openAbout}>关于</button><button className="nav-join" onClick={openJoin}>加入社群</button></nav>
      <div className="mobile-nav"><button className="nav-join" onClick={openJoin}>加入社群</button><button ref={menuButton} className="menu-button" aria-expanded={menuOpen} aria-controls="mobile-menu" onClick={()=>setMenuOpen(v=>!v)}>{menuOpen?'收起':'菜单'}</button></div>
      <nav className="mobile-menu" id="mobile-menu" aria-label="手机导航" hidden={!menuOpen}><a href="#how-it-works" onClick={()=>setMenuOpen(false)}>如何使用</a><a href="#scenery" onClick={()=>setMenuOpen(false)}>太原风景线</a><a href="#routes" onClick={()=>setMenuOpen(false)}>本地地图</a><a href="#community" onClick={()=>setMenuOpen(false)}>骑友社群</a><a href="#faq" onClick={()=>setMenuOpen(false)}>常见问题</a><button onClick={openAbout}>关于 VELO</button></nav>
    </header>
    <main>
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-art" aria-hidden="true"><img className="hero-photo" src="/assets/fenhe-sunset.png" alt="" fetchPriority="high" /></div>

        <div className="hero-copy">
          <p className="eyebrow">太原及周边骑行路线智能体</p>
          <h1 id="hero-title">太原<span className="title-comma">，</span>自有好路。</h1>
          <p className="hero-description">从汾河两岸，到群山深处。<br />寻一条与你相宜的路。</p>
          <a className="explore-button" href="#routes">探索路线</a>
        </div>
        <p className="photo-credit">汾河二库 · 阁楼</p>
        <a className="scroll-cue" href="#how-it-works" aria-label="了解如何使用 VELO"><span /></a>
      </section>
      <ProductDemo onMap={jumpToMap} onJoin={openJoin}/>
      <CommunityStats/>
      <ScenicGallery onOpen={setActivePlace} onMap={jumpToMap}/>
      <MapSection request={mapRequest} onReady={settleLowerAnchor}/>
      <FAQ/>
      <ClubSection onJoin={openJoin} onOpen={setActivePlace}/>
      <SiteFooter onJoin={openJoin} onAbout={openAbout}/>
    </main>
    <dialog ref={dialogRef} className={`detail-dialog ${aboutOpen||joinOpen ? 'about-dialog' : ''} ${joinOpen?'join-dialog':''}`} aria-labelledby="dialog-title" onCancel={closeDialog} onClick={event => {if(event.target===event.currentTarget)closeDialog()}}>
      <div className="dialog-inner"><button className="dialog-close" onClick={closeDialog} autoFocus>关闭</button>
        {activePlace && <><SceneImage scene={activePlace} className="dialog-scene" loading="eager"/><div className="dialog-copy"><p className="eyebrow">{activePlace.place}</p><h2 id="dialog-title">{activePlace.name}</h2><p>{activePlace.description}</p>{activePlace.segmentId&&<button className="dialog-map-link" onClick={()=>jumpToMap(activePlace.segmentId)}>查看相关赛段 · {activePlace.segmentLabel}</button>}</div></>}
        {aboutOpen && <div className="about-copy"><p className="wordmark"><span aria-hidden="true" />VELO</p><h2 id="dialog-title">太原，自有好路。</h2><p>从汾河两岸，到群山深处。<br />寻一条与你相宜的路。</p><p className="about-description">VELO 是面向太原及周边的骑行路线智能体，帮助骑友发现值得骑的路线，找到适合自己的下一程。通过骑友社群，付费使用服务。</p><div className="about-company"><p>{community.company}</p><p>开发与运营</p><button onClick={openJoin}>微信联系 · {community.wechatId}</button><a href={community.privacyUrl} target="_blank" rel="noreferrer">隐私政策</a></div></div>}
        {joinOpen&&<CommunityDialog/>}
      </div>
    </dialog>
  </>;
}
