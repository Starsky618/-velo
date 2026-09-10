import {useEffect,useRef} from 'react';
// Actual Strava longitude/latitude samples projected to Web Mercator; no inferred bends.
export function RouteThumb({segment,className=''}) {
 const ref=useRef(null);
 useEffect(()=>{
  const canvas=ref.current;if(!canvas||!segment)return;
  const projected=segment.coordinates.map(([lon,lat])=>[lon*Math.PI/180,Math.log(Math.tan(Math.PI/4+lat*Math.PI/360))]);
  const xs=projected.map(p=>p[0]),ys=projected.map(p=>p[1]);
  const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
  const paint=()=>{const {width,height}=canvas.getBoundingClientRect();if(!width||!height)return;const dpr=Math.min(window.devicePixelRatio||1,2);canvas.width=width*dpr;canvas.height=height*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);const pad=9,scale=Math.min((width-2*pad)/(maxX-minX||1),(height-2*pad)/(maxY-minY||1));const dx=(width-(maxX-minX)*scale)/2,dy=(height-(maxY-minY)*scale)/2;ctx.beginPath();projected.forEach(([x,y],i)=>{const a=dx+(x-minX)*scale,b=height-dy-(y-minY)*scale;i?ctx.lineTo(a,b):ctx.moveTo(a,b)});ctx.strokeStyle=getComputedStyle(canvas).color;ctx.lineWidth=1.8;ctx.lineCap='round';ctx.lineJoin='round';ctx.stroke();};
  const observer=new ResizeObserver(paint);observer.observe(canvas);paint();return()=>observer.disconnect();
 },[segment]);
 return <canvas ref={ref} className={`route-thumb ${className}`} role="img" aria-label={`${segment.name}的来源轨迹轮廓`}/>;
}
