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
check($('hero').innerHTML.length>200, 'hero renderizado');
check($('metrics').children.length===5, 'cinco indicadores', String($('metrics').children.length));
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

console.log('\nInteraccion: acciones rapidas (deben alternar)');
const btnUrg = () => $('hero').querySelector('[data-quick="urgencia"]');
btnUrg().dispatchEvent(new dom.window.Event('click'));
check(visibles()===5, 'accion rapida "solo con urgencia" aplica', String(visibles()));
check(btnUrg().classList.contains('on'), 'el boton queda marcado como activo', btnUrg().className);
btnUrg().dispatchEvent(new dom.window.Event('click'));
check(visibles()===10, 'segundo clic anula el filtro', String(visibles()));
check(!btnUrg().classList.contains('on'), 'el boton vuelve a estado inactivo', btnUrg().className);

const btnDir = () => $('hero').querySelector('[data-quick="directo"]');
btnDir().dispatchEvent(new dom.window.Event('click'));
const conDirecto = visibles();
btnDir().dispatchEvent(new dom.window.Event('click'));
check(visibles()===10 && conDirecto<10, 'impacto directo alterna', `${conDirecto} -> ${visibles()}`);

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

console.log('\nUltimas iniciativas y ficha emergente');
const recientes = $('hero').querySelectorAll('[data-ficha]');
check(recientes.length===3, 'el encabezado muestra tres iniciativas', String(recientes.length));
const fechaDe = b => Date.parse(
  (DATOS.proyectos.find(p=>p.boletin===b)||{}).ultimo_movimiento||'')||0;
const bols = [...recientes].map(b=>b.dataset.ficha);
check(fechaDe(bols[0])>=fechaDe(bols[1]) && fechaDe(bols[1])>=fechaDe(bols[2]),
      'estan ordenadas de mas reciente a mas antigua', bols.join(' > '));

check($('modal').hidden===true, 'la ficha arranca cerrada');
recientes[0].dispatchEvent(new dom.window.Event('click'));
check($('modal').hidden===false, 'clic en una iniciativa abre la ficha');
check($('modal').textContent.includes(bols[0]), 'la ficha corresponde al boletin', bols[0]);
check($('modal').querySelector('.timeline')!==null, 'la ficha incluye la tramitacion');
check($('modal').querySelector('.modal-links a')!==null, 'la ficha incluye enlaces a las fuentes');
check($('modal').querySelector('.kv div')!==null, 'la ficha incluye los datos de estado');

// Clic dentro del recuadro: no debe cerrar.
$('modal').querySelector('.modal').dispatchEvent(
  new dom.window.MouseEvent('click',{bubbles:true}));
check($('modal').hidden===false, 'clic dentro de la ficha no la cierra');

// Clic en el fondo: debe cerrar.
$('modal').dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
check($('modal').hidden===true, 'clic fuera de la ficha la cierra');

// Tecla Escape.
recientes[0].dispatchEvent(new dom.window.Event('click'));
dom.window.document.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape'}));
check($('modal').hidden===true, 'la tecla Escape cierra la ficha');

// Boton de cierre.
recientes[0].dispatchEvent(new dom.window.Event('click'));
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
