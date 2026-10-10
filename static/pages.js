const node = (tag, text, cls) => {const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e;};
const labels={UPC:'Upcoming',ONG:'Ongoing',CMP:'Completed',CNL_U:'Cancelled by customer',CNL_S:'Cancelled by RideWise',NSH:'No-show'};
const money=v=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(Number(v||0));
const stamp=v=>v ? new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(v.replace(' ','T')+'Z'))+' IST' : '—';
const title=v=>String(v||'').replaceAll('_',' ').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());
function table(columns,rows,onClick){
  const wrap=node('div',undefined,'data-table-wrap'),t=node('table',undefined,'data-table');
  const head=node('thead'),hr=node('tr');for(const [,label] of columns)hr.append(node('th',label));head.append(hr);t.append(head);
  const body=node('tbody');
  for(const r of rows){const tr=node('tr');for(const [key,,format] of columns){const cell=node('td');const value=format?format(r[key],r):r[key]??'—';cell.append(value instanceof Node?value:document.createTextNode(String(value)));tr.append(cell);}if(onClick){tr.classList.add('clickable-row');tr.addEventListener('click',event=>{if(!event.target.closest('button'))onClick(r);});}body.append(tr);}
  t.append(body);wrap.append(t);if(!rows.length)wrap.append(node('p','No matching records.','page-empty'));return wrap;
}
function paymentTable(rows){return table([['payment_id','Payment'],['payment_type','Type',title],['amount','Amount excl. GST',money],['gst_amount','GST',money],['amount','Total incl. GST',(_,r)=>money(Number(r.amount||0)+Number(r.gst_amount||0))],['payment_status','Status',title],['payment_method','Method',title],['paid_at','Recorded time',stamp]],rows);}
function chart(name,values,donut=false){
  const card=node('section',undefined,'chart-card');card.append(node('h3',name));
  const canvas=node('canvas');canvas.width=420;canvas.height=200;canvas.setAttribute('role','img');canvas.setAttribute('aria-label',name+': '+values.map(v=>v.label+' '+v.count).join(', '));
  const c=canvas.getContext('2d'),colors=['#5CB52E','#245C18','#a4cf8d','#101410','#788772','#d9e5d2'];
  if(donut){const total=values.reduce((n,v)=>n+v.count,0);let start=-Math.PI/2;for(const [i,v]of values.entries()){const end=start+(total?v.count/total:0)*Math.PI*2;c.beginPath();c.arc(210,100,72,start,end);c.arc(210,100,43,end,start,true);c.closePath();c.fillStyle=colors[i%colors.length];c.fill();start=end;}c.fillStyle='#101410';c.font='bold 24px Segoe UI';c.textAlign='center';c.fillText(String(total),210,108);}
  else{const max=Math.max(1,...values.map(v=>v.count)),height=Math.min(30,160/Math.max(1,values.length));for(const[i,v]of values.entries()){const y=10+i*(height+6);c.fillStyle='#556052';c.font='12px Segoe UI';c.fillText(title(v.label).slice(0,21),8,y+height*.7);c.fillStyle=colors[i%colors.length];c.fillRect(155,y,220*v.count/max,height);c.fillStyle='#101410';c.fillText(String(v.count),382,y+height*.7);}}
  card.append(canvas);const legend=node('div',undefined,'chart-legend');for(const v of values)legend.append(node('span',title(v.label)+': '+v.count));card.append(legend);return card;
}

export class WorkspacePages {
  constructor(hooks){
    this.hooks=hooks;this.root=document.getElementById('pageContent');this.version=0;this.tab='customers';this.bookingTab='upcoming';this.filters={};
    document.getElementById('myBookingsNav').addEventListener('click',()=>this.show('bookings'));
    document.getElementById('dashboardNav').addEventListener('click',()=>this.show('dashboard'));
    document.getElementById('policiesNav').addEventListener('click',()=>this.show('policies'));
    document.getElementById('pageMenu').addEventListener('change',e=>e.target.value==='chat'?this.hooks.chat():this.show(e.target.value));
    window.addEventListener('popstate',()=>{const page=location.pathname.slice(1);if(['policies','bookings','dashboard'].includes(page))this.show(page,false);else this.hooks.chat(false);});
  }
  syncRole(){
    this.version++;this.root.replaceChildren();const s=this.hooks.session();
    document.getElementById('myBookingsNav').classList.toggle('hidden',s?.role!=='customer');
    document.getElementById('dashboardNav').classList.toggle('hidden',s?.role!=='support_agent');
    const menu=document.getElementById('pageMenu');menu.replaceChildren();
    for(const[value,label]of [['chat','Chat'],['policies','Policies'],...(s?.role==='customer'?[['bookings','My bookings']]:[]),...(s?.role==='support_agent'?[['dashboard','Dashboards']]:[])]){const o=node('option',label);o.value=value;menu.append(o);}
    this.filters={};
  }
  clear(){this.version++;this.root.replaceChildren();this.filters={};}
  async openPath(){const p=location.pathname.slice(1);if(['policies','bookings','dashboard'].includes(p))await this.show(p,false);}
  async fetch(path,params={}){
    const s=this.hooks.session();if(!s)throw new Error('Start a permitted session first.');
    const query=new URLSearchParams({...params,session_id:s.session_id});return (await this.hooks.api(path+'?'+query)).json();
  }
  button(text,action,cls='secondary'){const b=node('button',text,cls);b.type='button';b.addEventListener('click',action);return b;}
  evidence(data,container=this.root){if(data.evidence?.length)container.append(this.button('Inspect executed SQL ↗',()=>this.hooks.evidence(data.evidence),'secondary sql-proof'));}
  heading(titleText,description){const h=node('div',undefined,'page-heading');h.append(node('div','RIDEWISE WORKSPACE','eyebrow'),node('h2',titleText),node('p',description));this.root.append(h);}
  cards(values){const strip=node('div',undefined,'metric-cards');for(const[label,value]of values){const card=node('div',undefined,'metric-card');card.append(node('span',label),node('strong',String(value)));strip.append(card);}this.root.append(strip);}
  async show(page,push=true){
    const s=this.hooks.session();if(!s){this.hooks.login();return;}
    if(page==='dashboard'&&s.role!=='support_agent'||page==='bookings'&&s.role!=='customer'){this.hooks.chat();return;}
    const version=++this.version;this.current=page;this.root.replaceChildren(node('p','Loading permitted records…','page-empty'));
    document.getElementById('messages').classList.add('hidden');document.getElementById('composerWrap').classList.add('hidden');this.root.classList.remove('hidden');document.body.classList.add('page-view');
    document.getElementById('pageTitle').textContent={policies:'Policy library',bookings:'My bookings',dashboard:'Support dashboards'}[page];document.getElementById('pageMenu').value=page;
    for(const[id,name]of [['conversationNav','chat'],['policiesNav','policies'],['myBookingsNav','bookings'],['dashboardNav','dashboard']])document.getElementById(id).classList.toggle('active',page===name);
    if(push&&location.pathname!=='/'+page)history.pushState({},'', '/'+page);
    try{
      if(page==='policies'){const data=await(await this.hooks.api('/api/policies')).json();if(version!==this.version)return;this.root.replaceChildren();this.renderPolicies(data);return;}
      const data=page==='bookings'?await this.fetch('/api/my/bookings',{tab:this.bookingTab}):await this.fetch('/api/dashboard/'+({customers:'customers',hubs:'hubs',bookings:'bookings',damage:'damage'}[this.tab]),this.filters);
      if(version!==this.version||s.session_id!==this.hooks.session()?.session_id)return;
      this.root.replaceChildren();if(page==='bookings')this.renderMyBookings(data);else this.renderDashboard(data);this.evidence(data);
    }catch(e){if(version===this.version){this.root.replaceChildren(node('p',e.message,'error page-empty'));if(page==='dashboard')this.root.append(this.button('Reset filters',()=>{this.filters={};this.show('dashboard',false);}));}}
  }
  renderPolicies(list){
    this.heading('The original policy library','Read the supplied documents. Refund policy versions are shown separately; browsing a document does not imply it was used in an answer.');
    const grid=node('div',undefined,'policy-grid');
    const names={rental:'Rental agreement & terms',refund_v1:'Cancellation & refunds · v1',refund_v2:'Cancellation & refunds · v2',penalty:'Late return & damage penalties',ev:'EV guide & FAQ'};
    for(const p of list){const card=node('article',undefined,'policy-card');card.append(node('span','PDF','eyebrow'),node('h3',names[p.key]||p.filename),node('p',p.filename),node('small',p.reviewed?'Reviewed source hash matches':'Source changed · review required'));
      const a=node('a','Open original PDF ↗','pdf-link');a.href='/api/policies/'+p.key;a.target='_blank';a.rel='noopener';a.addEventListener('click',async e=>{e.preventDefault();const blank=window.open('','_blank');try{const response=await this.hooks.api(a.getAttribute('href'));const url=URL.createObjectURL(await response.blob());this.hooks.blob(url);if(blank){blank.opener=null;blank.location=url;}else card.append(node('p','Allow popups to open the PDF.','error'));}catch(err){blank?.close();card.append(node('p',err.message,'error'));}});card.append(a);grid.append(card);}
    this.root.append(grid);
  }
  renderMyBookings(data){
    this.heading('Your rides, in one place','Only the linked customer’s bookings are shown. All times are IST. Past includes completed rides and no-shows.');
    const tabs=node('div',undefined,'page-tabs');for(const[name,label]of [['upcoming','Upcoming'],['ongoing','Ongoing'],['past','Past'],['cancelled','Cancelled']]){const codes={upcoming:['UPC'],ongoing:['ONG'],past:['CMP','NSH'],cancelled:['CNL_U','CNL_S']}[name];const count=data.counts.filter(c=>codes.includes(c.label)).reduce((n,c)=>n+c.count,0);tabs.append(this.button(label+' · '+count,()=>{this.bookingTab=name;this.show('bookings',false);},this.bookingTab===name?'selected':'secondary'));}this.root.append(tabs);
    const grid=node('div',undefined,'booking-grid');for(const r of data.rows){const card=node('article',undefined,'booking-card');card.append(node('span',labels[r.booking_status],'record-status'),node('h3',r.booking_id),node('p',r.model+' · '+title(r.vehicle_type)),node('p',r.hub_name),node('p','Start: '+stamp(r.scheduled_start)),node('p','End: '+stamp(r.scheduled_end)));
      const details=node('details');details.append(node('summary','Payments, refunds & damage'));details.addEventListener('toggle',()=>{if(details.open&&!details.dataset.loaded)this.loadBookingDetails(r.booking_id,details,true);});card.append(details);grid.append(card);}if(!data.rows.length)grid.append(node('p','No bookings in this category.','page-empty'));this.root.append(grid);
  }
  async loadBookingDetails(id,container,own=false){
    if(container.dataset.loaded)return;container.dataset.loaded='loading';const body=node('div','Loading details…','booking-detail');container.append(body);
    try{const d=await this.fetch((own?'/api/my/bookings/':'/api/dashboard/bookings/')+id);body.replaceChildren(node('h4','Payments · GST shown separately'),paymentTable(d.payments),node('h4','Recorded refunds'),paymentTable(d.refunds),node('h4','Damage claim status'),table([['report_id','Report'],['damage_category','Category',title],['claim_status','Claim status',title],['assessed_cost','Assessed cost',money]],d.damage),node('p','Refund amounts retain their negative sign. Only successful transactions represent recorded settled amounts. Assessed damage is not automatically a paid charge.','muted'));this.evidence(d,body);container.dataset.loaded='true';}
    catch(e){body.textContent=e.message;delete container.dataset.loaded;}
  }
  dashboardTabs(){const tabs=node('div',undefined,'page-tabs');for(const[key,label]of [['customers','Customers'],['hubs','Hubs & Vehicles'],['bookings','Bookings & Payments'],['damage','Damage Reports']])tabs.append(this.button(label,()=>{this.tab=key;this.filters={};this.show('dashboard',false);},this.tab===key?'selected':'secondary'));this.root.append(tabs);}
  filterForm(specs){
    const form=node('form',undefined,'dashboard-filters');const controls=[];
    for(const[key,label,options,type]of specs){const field=node('label',label);let input;if(options){input=node('select');const all=node('option','All');all.value='';input.append(all);for(const v of options){const o=node('option',labels[v]||title(v));o.value=v;input.append(o);}}else{input=node('input');input.type=type||'text';if(key==='customer_id')input.placeholder='CUST0001';}input.name=key;input.value=this.filters[key]||'';field.append(input);form.append(field);controls.push(input);}
    const submit=node('button','Apply filters','primary');submit.type='submit';form.append(submit,this.button('Reset',()=>{this.filters={};this.show('dashboard',false);}));form.addEventListener('submit',e=>{e.preventDefault();this.filters=Object.fromEntries(controls.filter(c=>c.value).map(c=>[c.name,c.value]));this.show('dashboard',false);});this.root.append(form);
  }
  paginate(data){if(data.total<=data.page_size)return;const bar=node('div',undefined,'pagination');bar.append(node('span',`${data.offset+1}–${Math.min(data.total,data.offset+data.rows.length)} of ${data.total}`));const prev=this.button('Previous',()=>{this.filters.offset=Math.max(0,data.offset-data.page_size);this.show('dashboard',false);});prev.disabled=data.offset===0;const next=this.button('Next',()=>{this.filters.offset=data.offset+data.page_size;this.show('dashboard',false);});next.disabled=data.offset+data.page_size>=data.total;bar.append(prev,next);this.root.append(bar);}
  renderDashboard(d){
    this.heading('Support operations','Read-only records for your active Support Agent session. Times are IST; amounts are INR, with GST separate.');this.dashboardTabs();
    if(this.tab==='customers'){
      this.filterForm([['kyc','KYC status',['VERIFIED','PENDING','REJECTED']],['tier','Tier',['GOLD','SILVER','STANDARD']],['city','City',d.city_options]]);
      this.cards([['Customers',d.total],...['VERIFIED','PENDING','REJECTED'].map(v=>['KYC '+title(v),d.kyc.find(r=>r.label===v)?.count||0]),...['GOLD','SILVER','STANDARD'].map(v=>[title(v),d.tiers.find(r=>r.label===v)?.count||0])]);
      const charts=node('div',undefined,'dashboard-charts');charts.append(chart('KYC status',d.kyc,true),chart('Tier split',d.tiers),chart('Customers by city',d.cities));this.root.append(charts,node('p','Names are masked. Phone, email, date of birth and licence number are excluded. Select a customer to view their bookings.','muted'));
      this.root.append(table([['customer_id','Customer ID',v=>this.button(v,()=>this.customerBookings(v),'table-link')],['full_name','Name · masked'],['city','City'],['customer_tier','Tier',title],['kyc_status','KYC',title],['created_at','Joined',stamp]],d.rows,r=>this.customerBookings(r.customer_id)));this.paginate(d);
    }else if(this.tab==='hubs'){
      this.filterForm([['hub','Hub',d.hub_options]]);this.cards([['Vehicles',d.total],...['ACTIVE','MAINTENANCE','RETIRED'].map(v=>[title(v),d.rows.filter(r=>r.status===v).length])]);
      for(const hub of [...new Set(d.rows.map(r=>r.hub_name))]){const hubRows=d.rows.filter(r=>r.hub_name===hub),section=node('section',undefined,'hub-card');section.append(node('h3',hub+' · '+hubRows.length+' vehicles'),node('p',['ACTIVE','MAINTENANCE','RETIRED'].map(v=>title(v)+': '+hubRows.filter(r=>r.status===v).length).join(' · ')));
        for(const type of [...new Set(hubRows.map(r=>r.vehicle_type))]){const typeRows=hubRows.filter(r=>r.vehicle_type===type),group=node('details');group.append(node('summary',title(type)+' · '+typeRows.length));for(const model of [...new Set(typeRows.map(r=>r.model))]){const rows=typeRows.filter(r=>r.model===model),inner=node('details');inner.append(node('summary',model+' · '+rows.length));inner.append(table([['vehicle_id','Vehicle'],['registration_no','Registration'],['hourly_rate','Hourly rate',money],['daily_rate','Daily rate',money],['battery_capacity_kwh','Battery · kWh',v=>v??'Not EV'],['status','Status',title],['commissioned_on','Commissioned'],['ongoing_booking','Ongoing booking',v=>v?'Yes · ONG record':'No']],rows));group.append(inner);}section.append(group);}this.root.append(section);}if(!d.rows.length)this.root.append(node('p','No vehicles match this hub.','page-empty'));
    }else if(this.tab==='bookings'){
      this.filterForm([['status','Booking status',Object.keys(labels)],['from','Start date · IST',null,'date'],['to','End date · IST',null,'date'],['hub','Hub',d.hub_options],['customer_id','Customer ID'],['payment_type','Payment type',['BOOKING','DEPOSIT','PENALTY','REFUND']],['payment_status','Payment status',['SUCCESS','FAILED','PENDING']]]);
      this.cards([['Bookings',d.total],['Late returns',d.flags.late_returns||0],['Failed/pending payment flags',d.flags.payment_attention||0]]);this.root.append(chart('Booking status',d.counts),node('h3','Payment totals by type and status'),node('p','Filtered totals cover all matching records, not only this page. Refunds remain negative; failed/pending transactions are shown separately. Date filters use scheduled pickup in IST.','muted'),table([['payment_type','Type',title],['payment_status','Status',title],['transactions','Transactions'],['amount_ex_gst','Amount excl. GST',money],['gst_amount','GST',money]],d.payment_totals));
      const rows=d.rows.map(r=>({...r,details:r}));this.root.append(table([['booking_id','Booking'],['customer_id','Customer'],['model','Vehicle'],['hub_name','Hub'],['scheduled_start','Scheduled start',stamp],['scheduled_end','Scheduled end',stamp],['actual_return_at','Actual return',stamp],['booking_status','Status',v=>labels[v]],['late_return','Late',v=>v?'Late return':'—'],['payment_attention','Payment flag',v=>v?'Failed / pending':'—'],['details','Details',(_,r)=>{const det=node('details');det.append(node('summary','Payments & claims'));det.addEventListener('toggle',()=>{if(det.open&&!det.dataset.loaded)this.loadBookingDetails(r.booking_id,det);});return det;}]],rows));this.paginate(d);
    }else{
      this.filterForm([['claim_status','Claim status',['OPEN','CHARGED','WAIVED','DISPUTED']],['category','Category',['SCRATCH','DENT','TYRE','BATTERY','LOST_KEY','OTHER']],['severity','Severity',['LOW','MEDIUM','HIGH']]]);
      this.cards([['Damage reports',d.total],...d.claims.map(r=>[title(r.label)+' · assessed',money(r.assessed_cost)])]);const charts=node('div',undefined,'dashboard-charts');charts.append(chart('Claim status',d.claims),chart('Damage category',d.categories),chart('Severity',d.severities));this.root.append(charts,node('p','Assessed repair cost is shown by claim status. Open/disputed claims are not confirmed paid penalties. Expand a report for its description.','muted'));
      this.root.append(table([['report_id','Report',(_,r)=>{const det=node('details');det.append(node('summary',r.report_id));det.addEventListener('toggle',async()=>{if(!det.open||det.dataset.loaded)return;det.dataset.loaded='loading';try{const result=await this.fetch('/api/dashboard/damage/'+r.report_id);det.append(node('p',result.report.description,'damage-description'));this.evidence(result,det);det.dataset.loaded='true';}catch(e){det.append(node('p',e.message,'error'));delete det.dataset.loaded;}});return det;}],['booking_id','Booking'],['vehicle_id','Vehicle'],['damage_category','Category',title],['severity','Severity',title],['assessed_cost','Assessed cost',money],['claim_status','Claim status',title],['reported_by','Reported by',title],['reported_at','Reported',stamp]],d.rows));this.paginate(d);
    }
  }
  customerBookings(id){this.tab='bookings';this.filters={customer_id:id};this.show('dashboard',false);}
}
