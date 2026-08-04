import { JSDOM } from 'jsdom';
import fs from 'fs';

const html = fs.readFileSync('index.html','utf8');
const datos = fs.readFileSync('datos.json','utf8');
const DATOS = JSON.parse(datos);

const errores = [];
// El stub de fetch debe existir ANTES de que jsdom evalue el <script>,
// porque el tablero llama a cargar() en cuanto se parsea.
const dom = new JSDOM(html, {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://example.org/',
  beforeParse(window){
    window.fetch = async () => ({ ok:true, status:200, json: async () => JSON.parse(datos) });
    window.addEventListener('error', e => errores.push('window.error: '+e.message));
  },
});

await new Promise(r => setTimeout(r, 600));

const $ = id => dom.window.document.getElementById(id);
const txt = id => ($(id)?.textContent||'').trim();
let fallas = 0;
const check = (cond, desc, det='') => {
  if(cond) console.log('  ok   '+desc);
  else { console.log('  FALLA '+desc+(det?'  -> '+det:'')); fallas++; }
};

console.log('\nRender inicial del tablero');
check(txt('statusText').includes('activa'), 'estado de carga correcto', txt('statusText'));
check(txt('statusStamp').length>0, 'marca de tiempo presente', txt('statusStamp'));
check($('novedades').innerHTML.length>400, 'panel de novedades renderizado');
check($('niveles').children.length===3, 'tres tarjetas de nivel', String($('niveles').children.length));
check($('pipeline').children.length===5, 'cinco etapas en el itinerario', String($('pipeline').children.length));
check($('billList').querySelectorAll('.bill').length>0, 'listado de proyectos con filas',
      String($('billList').querySelectorAll('.bill').length));
check($('rankEjes').children.length>0, 'ranking de ejes');
check($('rankSectores').children.length>0, 'ranking de sectores');
check(txt('resultCount').match(/\d+/), 'contador de resultados', txt('resultCount'));
check($('footer').innerHTML.includes('Motor'), 'pie con auditoria');

// El demo tiene 9 vigentes de 10; el filtro por defecto excluye el publicado.
const visibles = () => parseInt(txt('resultCount').match(/(\d+)/)[1],10);
check(visibles()===10, 'filtro "solo en tramitacion" activo por omision', String(visibles()));

console.log('\nInteraccion: filtros');
$('fVigente').checked = false;
$('fVigente').dispatchEvent(new dom.window.Event('change'));
check(visibles()===11, 'desmarcar vigente incluye el proyecto publicado', String(visibles()));
$('fVigente').checked = true;
$('fVigente').dispatchEvent(new dom.window.Event('change'));

$('fImpacto').value='directo';
$('fImpacto').dispatchEvent(new dom.window.Event('change'));
check(visibles()===3, 'filtro por impacto directo', String(visibles()));
check($('activeFilters').children.length>=1, 'chip de filtro activo visible');

$('clearBtn').dispatchEvent(new dom.window.Event('click'));
check(visibles()===10, 'boton limpiar restablece la vista', String(visibles()));

console.log('\nInteraccion: busqueda y orden');
$('fQuery').value='18488';
$('applyBtn').dispatchEvent(new dom.window.Event('click'));
check(visibles()===1, 'busqueda por boletin', String(visibles()));
$('clearBtn').dispatchEvent(new dom.window.Event('click'));

$('sortBy').value='estancado';
$('sortBy').dispatchEvent(new dom.window.Event('change'));
const primerBoletin = $('billList').querySelector('.boletin')?.textContent;
check(primerBoletin==='16808-25', 'orden por mas tiempo detenidos', String(primerBoletin));
$('sortBy').value='prioridad';
$('sortBy').dispatchEvent(new dom.window.Event('change'));
check($('billList').querySelector('.boletin')?.textContent==='17700-05',
      'orden por prioridad', String($('billList').querySelector('.boletin')?.textContent));

console.log('\nInteraccion: filtros por clic en rankings y etapas (deben alternar)');
const fila = () => $('rankEjes').querySelector('[data-k]');
const ejeClave = fila().dataset.k;
fila().dispatchEvent(new dom.window.Event('click'));
const conEje = visibles();
check(conEje<10, 'clic en un eje filtra', String(conEje));
check($('fEje').value===ejeClave, 'el selector lateral queda sincronizado', $('fEje').value);
$('rankEjes').querySelector(`[data-k="${ejeClave}"]`).dispatchEvent(new dom.window.Event('click'));
check(visibles()===10, 'segundo clic en el mismo eje anula el filtro', String(visibles()));
check($('fEje').value==='', 'el selector lateral se limpia', $('fEje').value);

const etapa = () => $('pipeline').querySelector('[data-etapa]');
const etapaClave = etapa().dataset.etapa;
etapa().dispatchEvent(new dom.window.Event('click'));
check(visibles()<10, 'clic en la cabecera de una etapa filtra', String(visibles()));
$('pipeline').querySelector(`[data-etapa="${etapaClave}"]`).dispatchEvent(new dom.window.Event('click'));
check(visibles()===10, 'segundo clic en la etapa anula el filtro', String(visibles()));

console.log('\nJerarquia por niveles');
const nivelDe = p => p.nivel_impacto==='directo' ? 1
  : (p.nivel_impacto==='estructural'||p.nivel_impacto==='sectorial') ? 2
  : (p.ejes||[]).some(e=>['facultades_uaf','delitos_base','sujetos_obligados'].includes(e)) ? 2 : 3;
const vigentes = DATOS.proyectos.filter(p=>p.vigente!==false);
const cuenta = n => vigentes.filter(p=>nivelDe(p)===n).length;

check($('niveles').querySelectorAll('[data-nivel]').length===3, 'tres niveles clicables');
check($('niveles').querySelector('[data-nivel="1"] .n').textContent===String(cuenta(1)),
      'el conteo del nivel 1 cuadra', $('niveles').querySelector('[data-nivel="1"] .n').textContent);

const n1card = () => $('niveles').querySelector('[data-nivel="1"]');
n1card().dispatchEvent(new dom.window.Event('click'));
check(visibles()===cuenta(1), 'clic en nivel 1 filtra la vista', String(visibles()));
check($('fNivel').value==='1', 'el selector lateral se sincroniza', $('fNivel').value);
check(n1card().classList.contains('active'), 'la tarjeta de nivel queda marcada');
n1card().dispatchEvent(new dom.window.Event('click'));
check(visibles()===10, 'segundo clic anula el filtro de nivel', String(visibles()));
check($('fNivel').value==='', 'el selector se limpia', $('fNivel').value);

console.log('\nPanel de novedades');
const pulso = $('novedades').querySelectorAll('.news-pulse div');
check(pulso.length===4, 'cuatro indicadores de pulso', String(pulso.length));
const cols = $('novedades').querySelectorAll('.news-col');
check(cols.length===2, 'dos columnas: nivel 1 y nivel 2', String(cols.length));
check(cols[0].querySelector('.lvl1')!==null, 'la columna principal es la de nivel 1');
check(cols[1].querySelector('.lvl2')!==null, 'la segunda columna es la de nivel 2');

const fichas1 = cols[0].querySelectorAll('.feed-item[data-ficha]');
check(fichas1.length>0 && fichas1.length<=4, 'el nivel 1 muestra hasta cuatro tarjetas',
      String(fichas1.length));
const f = b => Date.parse((DATOS.proyectos.find(p=>p.boletin===b)||{}).ultimo_movimiento||'')||0;
const orden1 = [...fichas1].map(b=>b.dataset.ficha);
check(orden1.every((b,i)=>i===0||f(orden1[i-1])>=f(b)),
      'las novedades van de mas reciente a mas antigua', orden1.join(' > '));
check(orden1.every(b=>nivelDe(DATOS.proyectos.find(p=>p.boletin===b))===1),
      'la columna principal solo trae nivel 1');

const filas2 = cols[1].querySelectorAll('.feed-row[data-ficha]');
check([...filas2].every(b=>nivelDe(DATOS.proyectos.find(p=>p.boletin===b.dataset.ficha))===2),
      'la segunda columna solo trae nivel 2');

console.log('\nFicha emergente');
check($('modal').hidden===true, 'la ficha arranca cerrada');
fichas1[0].dispatchEvent(new dom.window.Event('click'));
check($('modal').hidden===false, 'clic en una novedad abre la ficha');
check($('modal').textContent.includes(orden1[0]), 'la ficha corresponde al boletin', orden1[0]);
check($('modal').querySelector('.lvl1')!==null, 'la ficha declara el nivel');
check($('modal').querySelector('.timeline')!==null, 'la ficha incluye la tramitacion');
check($('modal').querySelector('.modal-links a')!==null, 'la ficha incluye enlaces a las fuentes');
check($('modal').querySelector('.kv div')!==null, 'la ficha incluye los datos de estado');

$('modal').querySelector('.modal').dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
check($('modal').hidden===false, 'clic dentro de la ficha no la cierra');
$('modal').dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
check($('modal').hidden===true, 'clic fuera de la ficha la cierra');

fichas1[0].dispatchEvent(new dom.window.Event('click'));
dom.window.document.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape'}));
check($('modal').hidden===true, 'la tecla Escape cierra la ficha');

fichas1[0].dispatchEvent(new dom.window.Event('click'));
$('modalClose').dispatchEvent(new dom.window.Event('click'));
check($('modal').hidden===true, 'el boton de cierre funciona');

console.log('\nFicha desde el itinerario y desde el listado');
const chipItinerario = $('pipeline').querySelector('[data-boletin]');
chipItinerario.dispatchEvent(new dom.window.Event('click'));
check($('modal').hidden===false, 'clic en el itinerario abre la ficha');
check($('modal').textContent.includes(chipItinerario.dataset.boletin),
      'la ficha del itinerario corresponde al boletin');
$('modal').dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
check(visibles()===10, 'abrir la ficha no altera los filtros de la vista', String(visibles()));

$('billList').querySelector('[data-ficha]').dispatchEvent(new dom.window.Event('click'));
check($('modal').hidden===false, 'el listado abre la ficha completa');
$('modal').dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));

console.log('\nRevision manual');
$('clearBtn').dispatchEvent(new dom.window.Event('click'));
$('fRevision').checked = true;
$('fRevision').dispatchEvent(new dom.window.Event('change'));
check(visibles()===1, 'filtro de pendientes de revision', String(visibles()));
check($('billList').querySelector('.tag.revision')!==null, 'etiqueta de revision visible');
check($('billList').querySelector('.boletin')?.textContent==='18216-05',
      'el omnibus 18216-05 aparece en el tablero',
      String($('billList').querySelector('.boletin')?.textContent));
$('clearBtn').dispatchEvent(new dom.window.Event('click'));

console.log('\nEscape de contenido');
check(!$('billList').innerHTML.includes('<script>'), 'sin inyeccion de script en el listado');

console.log('\nErrores capturados:', errores.length ? errores : 'ninguno');
if(errores.length) fallas += errores.length;
console.log('\n'+'='.repeat(60));
console.log(fallas ? `FALLAS: ${fallas}` : 'TABLERO: todas las comprobaciones correctas');
process.exit(fallas?1:0);
