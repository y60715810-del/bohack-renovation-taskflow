
import {createSwarm} from '/static/vendor/swarm-rebuild/index.js';
const play=document.querySelector('#play'),stop=document.querySelector('#stop');
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let swarm;
function finish(){stop.hidden=true;play.hidden=false;}
play.onclick=()=>{
 if(reduced.matches)return;
 swarm?.destroy();
 play.hidden=true;stop.hidden=false;
 swarm=createSwarm({trigger:'manual',autoScroll:false,speed:2.6,maxHeight:window.innerHeight,maxItems:100,onComplete:()=>{swarm?.destroy();finish();}});
 swarm.start();
 // The engine resets host styles with !important; theme the host explicitly.
 document.querySelector('swarm-rebuild')?.style.setProperty('filter','grayscale(1)','important');
};
stop.onclick=()=>{swarm?.destroy();finish();};
reduced.addEventListener('change',()=>{swarm?.destroy();finish();play.hidden=reduced.matches;});
play.hidden=reduced.matches;
window.addEventListener('pagehide',()=>swarm?.destroy());
