export const labels = {entrada:'Presente solo en el corte final',salida:'Ausente en el corte final',cambio_estado:'Cambio de estado, periodo o zona',cambio_actividad:'Cambio de actividad',cambio:'Cambio de registro'};
export function filterChanges(rows, {district='',type='',search='',sort='district'}={}) {
  const q=search.toLocaleLowerCase('es').trim();
  return rows.filter(r=>(!district||r.district===district)&&(!type||r.type===type)&&(!q||[r.id,r.local_id,r.neighborhood,r.activity,r.district].join(' ').toLocaleLowerCase('es').includes(q))).sort((a,b)=>String(a[sort]??'').localeCompare(String(b[sort]??''),'es',{numeric:true})||String(a.id).localeCompare(String(b.id),'es',{numeric:true}));
}
export function csvCell(value){const s=String(value??'');return '"'+(/^[\s]*[=+@-]/.test(s)?"'"+s:s).replaceAll('"','""')+'"';}
export function toCSV(rows,meta={}){return '\uFEFF'+[['ID terraza','ID local','Distrito','Barrio','Actividad','Tipo','Antes','Después','Corte inicial','Corte final','Fuente','Licencia','Interpretación'],...rows.map(r=>[r.id,r.local_id,r.district,r.neighborhood,r.activity,labels[r.type]??r.type,r.before,r.after,meta.from_date,meta.to_date,meta.source_url,meta.license,'Diferencia administrativa; no apertura o cierre confirmado'])].map(row=>row.map(csvCell).join(';')).join('\r\n');}
export function validateData(data){
  if(!data||!data.meta||!Array.isArray(data.changes)||!['real','synthetic'].includes(data.meta.mode))throw Error('El conjunto no tiene un formato válido.');
  const m=data.meta, integer=n=>Number.isSafeInteger(n)&&n>=0;
  const date=s=>typeof s==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(s)&&Number.isFinite(Date.parse(s))&&new Date(s).toISOString().slice(0,10)===s;
  if(!date(m.from_date)||!date(m.to_date)||m.from_date>=m.to_date)throw Error('Las fechas de los cortes no son válidas.');
  if(!integer(m.total_changes)||!integer(m.displayed_changes)||m.displayed_changes!==data.changes.length||m.total_changes<m.displayed_changes)throw Error('Los totales del conjunto no son coherentes.');
  if(!m.counts||Array.isArray(m.counts)||typeof m.counts!=='object'||Object.entries(m.counts).some(([k,v])=>!Object.hasOwn(labels,k)||!integer(v))||Object.values(m.counts).reduce((a,b)=>a+b,0)!==m.total_changes)throw Error('El desglose de cambios no es coherente.');
  const ids=new Set(), counts={};
  for(const r of data.changes){
    if(!r||typeof r.id!=='string'||!r.id.trim()||['district','neighborhood','activity','type'].some(k=>typeof r[k]!=='string')||!Object.hasOwn(labels,r.type)||![r.before,r.after].every(v=>v===null||typeof v==='string'))throw Error('Hay un registro incompleto.');
    if(ids.has(r.id))throw Error('Hay identificadores de terraza duplicados.');
    ids.add(r.id);counts[r.type]=(counts[r.type]??0)+1;
  }
  for(const k of Object.keys(labels))if((counts[k]??0)>(m.counts[k]??0))throw Error('El desglose no corresponde a los registros.');
  return data;
}
export function coverageSummary(data){
  const m=data.meta, c=m.counts;
  const modifications=Object.entries(c).filter(([k])=>k!=='entrada'&&k!=='salida').reduce((n,[,v])=>n+v,0);
  return `${data.changes.length} de ${m.total_changes} diferencias publicadas · ${data.changes.length===m.total_changes?'Cobertura completa':'Selección parcial'} · Universo comparado: ${c.entrada??0} entradas, ${c.salida??0} salidas y ${modifications} modificaciones. No son aperturas confirmadas.`;
}
