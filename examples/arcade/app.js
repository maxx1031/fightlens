const $=id=>document.getElementById(id),v=$('video'),all=[],duration=DATA.t.at(-1)+1/DATA.fps;
const rounds=DATA.segments||[{start:0,end:duration,title:'Local arena',A:'BLACK KIT',B:'WHITE KIT'}],roundAt=t=>{const k=rounds.findIndex(s=>t>=s.start&&t<s.end);return k<0?rounds.length-1:k},roundName=k=>'ROUND '+String(k+1).padStart(2,'0');
rounds.forEach((s,k)=>all.push({t:s.start,type:roundName(k)+' START',who:s.A+' vs '+s.B,source:s.title}));
const winA=DATA.win_A||[],winPts=DATA.win_points||[],pct=x=>Math.round(x*100);
winPts.forEach(p=>all.push({t:p.t,type:'WIN PROB UPDATE',who:'A '+pct(p.A)+'% / B '+(100-pct(p.A))+'%',source:'Luna Decisions'}));
let lastFlash=null;
// Cosmos referee + Jev verdicts (yolo_branch/referee.py), shown in the exchange-status callout
// from the moment they would have come back: end of the clip + Cosmos latency.
const REF=DATA.referee||[],ended=()=>v.ended||v.currentTime>=duration-0.05;
const pretty=x=>(x||'').replace(/_/g,' ');
function headline(r){const c=r.cosmos||{};if(c.error)return{text:'COSMOS ERROR',tone:'muted'};const st=c.strikes||[],landed=st.filter(s=>s.outcome==='landed');
 if(landed.length){const who=[...new Set(landed.map(s=>s.attacker))].join('/');return{text:who+' LANDED'+(landed.length>1?' ×'+landed.length:''),tone:'landed'}}
 if(st.some(s=>s.outcome==='blocked'))return{text:'BLOCKED',tone:'blocked'};return{text:st.length?'NO CLEAN HIT':'NO STRIKE',tone:'muted'}}
function strikeLine(r){return(r.cosmos?.strikes||[]).slice(0,3).map(s=>s.attacker+' '+(s.move||s.limb)+' → '+s.target+' '+s.outcome).join(' · ')}
function jevLine(r){const d=r.jev?.direction?.choice;return d?'Jev: '+pretty(d)+(r.jev.evidence?' / '+pretty(r.jev.evidence.choice):''):'Jev: '+(r.jev?.error?'error':'—')}
REF.forEach(r=>{const h=headline(r);all.push({t:Math.min(r.available,duration-0.001),type:'COSMOS VERDICT',who:h.text+(r.cosmos?.advantage?' · adv '+r.cosmos.advantage:''),source:'Cosmos · clip '+r.t0.toFixed(1)+'–'+r.t1.toFixed(1)+'s'});
 if(r.jev?.direction)all.push({t:Math.min(r.available,duration-0.001),type:'JEV JUDGMENT',who:pretty(r.jev.direction.choice)+' / '+pretty(r.jev.evidence.choice),source:'Jev · '+r.jev.model})});
function showCallout(t,seg,engaged,known){const c=$('callout');
 const done=REF.filter(r=>r.t0>=seg.start&&r.t0<seg.end&&(r.available<=t||(ended()&&r.t1<=t+0.05)));const last=done.at(-1);
 const reviewing=REF.find(r=>r.t0<=t&&t<r.available&&!(ended()&&r.t1<=t+0.05));
 c.classList.remove('hot','verdict','landed','blocked');
 if(last&&(t-last.available<4||ended())){const h=headline(last);c.classList.add('verdict',h.tone);
  $('calloutLabel').textContent='COSMOS VERDICT · '+last.t0.toFixed(1)+'–'+last.t1.toFixed(1)+'s'+(last.available>duration?' · returned after the clip ended':'');
  $('state').textContent=h.text;$('stateText').textContent=(last.cosmos?.note||'')+'\n'+strikeLine(last)+'\n'+jevLine(last);return}
 $('calloutLabel').textContent='EXCHANGE STATUS';
 $('state').textContent=!known?'UNKNOWN':engaged?'ENGAGE!':'CLEAR';c.classList.toggle('hot',!!engaged);
 $('stateText').textContent=!known?'Insufficient data':engaged?(reviewing?'Exchange active · Cosmos reviewing this clip…':'Exchange active · Stay alert'):reviewing?'Cosmos reviewing the last exchange…':last?'Last verdict: '+headline(last).text:'Current rule: no engagement'}
const hits=DATA.hits||[],ZONES=[['head','HEAD'],['body','BODY'],['leg','LEGS']];
hits.forEach(h=>all.push({t:h.t,type:h.contact?'CONTACT CANDIDATE':'STRIKE · NO CONTACT',who:h.attacker+' → '+h.defender+' '+h.zone,source:h.limb+' · pose geometry'}));
const BODY='<svg viewBox="0 0 120 240" aria-hidden="true"><circle class="z" data-z="head" cx="60" cy="24" r="17"/><path class="z" data-z="body" d="M34 48h52l16 6 8 66-12 4-8-50v50H38V74l-8 50-12-4 8-66z"/><path class="z" data-z="leg" d="M38 126h44l-4 108H63l-3-78-3 78H42z"/></svg>';
for(const who of ['A','B'])$('heat'+who).outerHTML='<div class="hcard '+who.toLowerCase()+'" id="heat'+who+'"><div class="who"><b>FIGHTER '+who+'</b><span id="heatName'+who+'"></span></div>'+BODY+'<ul>'+ZONES.map(([z,l])=>'<li>'+l+'<b id="n'+who+z+'">0</b></li>').join('')+'</ul><div class="last" id="heatLast'+who+'"></div></div>';
const heatColor=n=>n<=0?'#2b2f38':['#6e2a25','#a3332b','#d63b30','#ff4a3d'][Math.min(n,4)-1];
let heatSeen=new Set();
for(let i=0;i<DATA.t.length;i++){
 if(DATA.engaged[i]!==null&&(i===0||DATA.engaged[i]!==DATA.engaged[i-1]))all.push({t:DATA.t[i],type:DATA.engaged[i]?'ENGAGEMENT START':'ENGAGEMENT END',who:'A / B',source:'existing rule'});
 for(const who of ['A','B'])if(DATA['ext_'+who][i]!=null&&DATA['ext_'+who][i]>=.9&&(i===0||DATA['ext_'+who][i-1]==null||DATA['ext_'+who][i-1]<.9))all.push({t:DATA.t[i],type:'PUNCH CANDIDATE',who,source:'extension ≥ 0.9'});
}
all.sort((a,b)=>a.t-b.t);
const fmt=x=>x==null?'—':x.toFixed(2);let prev=-1,visibleCount=-1;
function update(){const t=v.currentTime,i=Math.min(DATA.t.length-1,Math.max(0,Math.round(t*DATA.fps)));$('seek').value=t;const k=roundAt(t),seg=rounds[k];$('clock').textContent=String(Math.max(0,Math.ceil(seg.end-t))).padStart(2,'0');$('round').textContent=roundName(k);$('arena').textContent=seg.title.toUpperCase()+' / '+roundName(k);$('kitA').textContent='PLAYER 01 / '+seg.A;$('kitB').textContent=seg.B+' / PLAYER 02';$('time').textContent=t.toFixed(2)+' / '+duration.toFixed(2);$('play').textContent=v.paused?'▶ Play':'Ⅱ Pause';if(i===prev)return;prev=i;
 const engaged=DATA.engaged[i],known=engaged!=null;showCallout(t,seg,engaged,known);$('risk').textContent=!known?'Tracking uncertain':engaged?'Engagement alert':'Alert cleared';$('light').style.color=!known?'#888':engaged?'#ff6552':'#89e39e';
 const wa=winA[i],pts=winPts.filter(p=>p.t>=seg.start&&p.t<=t+1e-6),wLast=pts.at(-1),wPrev=pts.at(-2);$('wpA').textContent=wa==null?'—':pct(wa)+'%';$('wpB').textContent=wa==null?'—':(100-pct(wa))+'%';$('wpFill').style.width=(wa==null?50:wa*100)+'%';$('wpInA').textContent=wa==null?'':'A '+pct(wa)+'%';$('wpInB').textContent=wa==null?'':(100-pct(wa))+'% B';$('wpInA').style.visibility=wa!=null&&wa>=.12?'visible':'hidden';$('wpInB').style.visibility=wa!=null&&wa<=.88?'visible':'hidden';document.querySelector('.wp-bar').classList.toggle('empty',wa==null);$('wpStatus').textContent=!wLast?'No estimate yet this round':t-wLast.t<1.05?'Updated at '+wLast.t.toFixed(1)+'s · engaged second':'Held since '+wLast.t.toFixed(1)+'s · no engagement, not sampled';$('wpTrend').textContent=wLast&&wPrev?'A '+(pct(wLast.A)-pct(wPrev.A)>=0?'+':'')+(pct(wLast.A)-pct(wPrev.A))+' pts':'';if(wLast&&wLast!==lastFlash){lastFlash=wLast;const w=document.querySelector('.winprob');w.classList.add('flash');setTimeout(()=>w.classList.remove('flash'),500)}
 for(const who of ['A','B']){const got=hits.filter(h=>h.contact&&h.defender===who&&h.t>=seg.start&&h.t<=t);$('heatName'+who).textContent=(who==='A'?seg.A:seg.B);for(const [z] of ZONES){const n=got.filter(h=>h.zone===z).length;$('n'+who+z).textContent=n;$('n'+who+z).classList.toggle('hot',n>0);const el=document.querySelector('#heat'+who+' [data-z="'+z+'"]');el.style.fill=heatColor(n)}const lastHit=got.at(-1);$('heatLast'+who).textContent=lastHit?'Last: '+lastHit.zone+' · '+lastHit.limb+' by '+lastHit.attacker+' · '+lastHit.t.toFixed(2)+'s':'No contact candidates this round';for(const h of got){const key=h.t+who+h.zone;if(!heatSeen.has(key)&&t-h.t<0.5){heatSeen.add(key);const el=document.querySelector('#heat'+who+' [data-z="'+h.zone+'"]');el.classList.remove('flash');void el.getBoundingClientRect();el.classList.add('flash')}}}
 const visible=all.filter(e=>e.t<=t),punch=visible.filter(e=>e.type==='PUNCH CANDIDATE'&&e.t>=seg.start);
 for(const who of ['A','B']){const reach=DATA['reach_'+who][i],ext=DATA['ext_'+who][i];const p=reach==null||ext==null?0:Math.round(Math.min(1,Math.max(0,1-reach/1.5)) * ext*100);$('bar'+who).style.width=p+'%';$('pressure'+who).textContent=reach==null||ext==null?'—':p;$('count'+who).textContent=String(punch.filter(e=>e.who===who).length).padStart(2,'0');}
 const last=punch.at(-1);$('move').textContent=last?last.who+' · Punch candidate / '+last.t.toFixed(2)+'s':'Waiting for an action';
 $('metrics').innerHTML=[['A win prob','win_A'],['Center distance','com_dist'],['A reach','reach_A'],['B reach','reach_B'],['A extension','ext_A'],['B extension','ext_B']].map(([label,key])=>'<div class="metric">'+label+'<strong>'+fmt(DATA[key][i])+'</strong></div>').join('');
 $('record').textContent=JSON.stringify({clip:DATA.clip,round:roundName(k),A:seg.A,B:seg.B,frame:i,t_s:DATA.t[i],engaged:DATA.engaged[i],win_A:winA[i]??null,com_dist:DATA.com_dist[i],reach_A:DATA.reach_A[i],reach_B:DATA.reach_B[i],ext_A:DATA.ext_A[i],ext_B:DATA.ext_B[i],source:'offline YOLO measurements'},null,2);
 if(visible.length!==visibleCount){visibleCount=visible.length;$('events').replaceChildren(...visible.slice().reverse().map(e=>{const tr=document.createElement('tr');for(const value of [e.t.toFixed(2)+'s',e.type,e.who,e.source]){const td=document.createElement('td');td.textContent=value;tr.append(td)}tr.tabIndex=0;tr.onclick=()=>{v.currentTime=e.t;update()};tr.onkeydown=k=>{if(k.key==='Enter')tr.click()};return tr}));}
}
$('play').onclick=()=>{if(v.paused)v.play().catch(()=>{$('stateText').textContent='Please press play again'});else v.pause()};$('reset').onclick=()=>{v.currentTime=0;update()};$('seek').oninput=e=>{v.currentTime=+e.target.value;update()};v.addEventListener('loadedmetadata',()=>{$('seek').max=v.duration;update()});v.addEventListener('seeked',update);v.addEventListener('play',()=>{prev=-1;update()});v.addEventListener('pause',()=>{prev=-1;update()});
function mode(back){document.body.classList.toggle('backend',back);$('console').hidden=!back;$('audience').classList.toggle('selected',!back);$('database').classList.toggle('selected',back);history.replaceState(null,'',back?'#database':'#audience')}$('audience').onclick=()=>mode(false);$('database').onclick=()=>mode(true);mode(location.hash!=='#audience');
$('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({clip:DATA.clip,source:'offline replay',rounds,events:all},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='fightlens-events.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};function loop(){update();requestAnimationFrame(loop)}loop();
