import { JSDOM } from 'jsdom';
import fs from 'fs';

const html = fs.readFileSync('index.html','utf8');
const datos = fs.readFileSync('datos.json','utf8');

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
check(visibles()===9, 'filtro "solo en tramitacion" activo por omision', String(visibles()));

console.log('\nInteraccion: filtros');
$('fVigente').checked = false;
$('fVigente').dispatchEvent(new dom.window.Event('change'));
check(visibles()===10, 'desmarcar vigente incluye el proyecto publicado', String(visibles()));
$('fVigente').checked = true;
$('fVigente').dispatchEvent(new dom.window.Event('change'));

$('fImpacto').value='directo';
$('fImpacto').dispatchEvent(new dom.window.Event('change'));
check(visibles()===3, 'filtro por impacto directo', String(visibles()));
check($('activeFilters').children.length>=1, 'chip de filtro activo visible');

$('clearBtn').dispatchEvent(new dom.window.Event('click'));
check(visibles()===9, 'boton limpiar restablece la vista', String(visibles()));

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

console.log('\nInteraccion: acciones rapidas y detalle');
const btnUrg = $('hero').querySelector('[data-quick="urgencia"]');
btnUrg.dispatchEvent(new dom.window.Event('click'));
check(visibles()===4, 'accion rapida "solo con urgencia"', String(visibles()));
$('hero').querySelector('[data-quick="urgencia"]').dispatchEvent(new dom.window.Event('click'));
check(visibles()===9, 'la accion rapida alterna', String(visibles()));

const expandir = $('billList').querySelector('[data-expand]');
expandir.dispatchEvent(new dom.window.Event('click'));
check($('billList').querySelector('.timeline')!==null, 'expandir muestra la linea de tramitacion');
check($('billList').querySelector('.evidence')!==null, 'expandir muestra la evidencia');

console.log('\nInteraccion: itinerario');
const chip = $('pipeline').querySelector('[data-boletin]');
check(chip!==null, 'el itinerario tiene proyectos clicables');
if(chip){
  chip.dispatchEvent(new dom.window.Event('click'));
  check(visibles()===1, 'clic en el itinerario filtra ese boletin', String(visibles()));
}

console.log('\nEscape de contenido');
check(!$('billList').innerHTML.includes('<script>'), 'sin inyeccion de script en el listado');

console.log('\nErrores capturados:', errores.length ? errores : 'ninguno');
if(errores.length) fallas += errores.length;
console.log('\n'+'='.repeat(60));
console.log(fallas ? `FALLAS: ${fallas}` : 'TABLERO: todas las comprobaciones correctas');
process.exit(fallas?1:0);
