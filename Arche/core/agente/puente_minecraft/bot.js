'use strict'
/*
 * bot.js - puente entre el agente de Arché (Python) y Minecraft (Mineflayer).
 *
 * Es un jugador-bot que entra a tu mundo y un servidor HTTP que SOLO escucha en
 * 127.0.0.1. El agente le pide el estado (GET /estado) y le manda acciones
 * (POST /accion). Aquí no hay inteligencia: solo percepción y acciones fiables.
 * Todo lo que piensa y decide está en Python.
 *
 *   GET  /ping          -> { ok, conectado }
 *   GET  /datos         -> recetas y herramientas por bloque (?version=1.20.4 si no hay conexión)
 *   POST /conectar      -> entra al mundo { host, puerto, usuario, version, auth }
 *   GET  /estado        -> estado del juego (?ligero=1 solo inventario)
 *   POST /accion        -> { nombre, args } -> { ok, mensaje, datos }
 *   POST /detener       -> corta lo que esté haciendo
 *   POST /desconectar   -> sale del mundo
 *
 * Los mensajes de error están en español y dicen QUÉ faltó, porque el agente
 * los lee para corregirse.
 */

const http = require('http')
const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder')
const { Vec3 } = require('vec3')

const { GoalNear, GoalGetToBlock } = goals

const argPuerto = process.argv.indexOf('--puerto')
const PUERTO = argPuerto >= 0 ? parseInt(process.argv[argPuerto + 1], 10) : 3921

let bot = null
let recipe = null // clase Recipe de prismarine-recipe (se crea al conectar)
let movimientos = null
let ocupado = false
let cancelado = false
const eventos = []

function evento (texto) {
  eventos.push(texto)
  while (eventos.length > 12) eventos.shift()
}

const dormir = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

class ErrorAccion extends Error {}

function revisarCancelado () {
  if (cancelado) throw new ErrorAccion('Acción cancelada por el usuario.')
}

// ---------------------------------------------------------------------------
// Nombres: acepta nombres internos (oak_log) y grupos (log, planks, wool, bed)
// ---------------------------------------------------------------------------
const GRUPOS = {
  log: (n) => n.endsWith('_log') || n.endsWith('_stem'),
  planks: (n) => n.endsWith('_planks'),
  wool: (n) => n.endsWith('_wool'),
  bed: (n) => n.endsWith('_bed'),
  sapling: (n) => n.endsWith('_sapling'),
  leaves: (n) => n.endsWith('_leaves'),
  boat: (n) => n.endsWith('_boat')
}

function limpiarNombre (nombre) {
  return String(nombre || '').trim().toLowerCase().replace(/^minecraft:/, '').replace(/\s+/g, '_')
}

function bloquesPorNombre (nombre) {
  const n = limpiarNombre(nombre)
  const todos = Object.values(bot.registry.blocksByName)
  if (GRUPOS[n]) return todos.filter((b) => GRUPOS[n](b.name))
  const exacto = bot.registry.blocksByName[n]
  return exacto ? [exacto] : []
}

function itemsPorNombre (nombre) {
  const n = limpiarNombre(nombre)
  const todos = Object.values(bot.registry.itemsByName)
  if (GRUPOS[n]) return todos.filter((i) => GRUPOS[n](i.name))
  const exacto = bot.registry.itemsByName[n]
  return exacto ? [exacto] : []
}

function itemEnInventario (nombre) {
  const candidatos = new Set(itemsPorNombre(nombre).map((i) => i.id))
  return bot.inventory.items().find((it) => candidatos.has(it.type)) || null
}

function inventarioPlano () {
  const inv = {}
  for (const it of bot.inventory.items()) inv[it.name] = (inv[it.name] || 0) + it.count
  return inv
}

// ---------------------------------------------------------------------------
// Movimiento
// ---------------------------------------------------------------------------
async function irA (meta, segundos = 60) {
  revisarCancelado()
  bot.pathfinder.setMovements(movimientos)
  let temporizador
  const limite = new Promise((resolve, reject) => {
    temporizador = setTimeout(() => {
      bot.pathfinder.stop()
      reject(new ErrorAccion('Tardé demasiado en llegar (no encuentro camino o está muy lejos).'))
    }, segundos * 1000)
  })
  try {
    await Promise.race([bot.pathfinder.goto(meta), limite])
  } catch (e) {
    if (e instanceof ErrorAccion) throw e
    if (cancelado) throw new ErrorAccion('Acción cancelada por el usuario.')
    throw new ErrorAccion('No pude llegar: ' + (e.message || e))
  } finally {
    clearTimeout(temporizador)
  }
}

function posTxt (p) {
  return `${Math.floor(p.x)},${Math.floor(p.y)},${Math.floor(p.z)}`
}

function distancia (p) {
  return Math.round(bot.entity.position.distanceTo(p) * 10) / 10
}

// ---------------------------------------------------------------------------
// Herramientas
// ---------------------------------------------------------------------------
const HERRAMIENTAS = /(pickaxe|_axe|shovel|hoe|sword|shears)$/

async function equiparMejorHerramienta (bloque) {
  const candidatos = bot.inventory.items().filter((i) => HERRAMIENTAS.test(i.name))
  let mejor = null
  let tiempoMejor = bloque.digTime(null, false, false, false)
  for (const it of candidatos) {
    const t = bloque.digTime(it.type, false, false, false)
    if (t < tiempoMejor) { mejor = it; tiempoMejor = t }
  }
  if (mejor) await bot.equip(mejor, 'hand')
}

function exigeHerramienta (bloque) {
  return bloque.harvestTools && Object.keys(bloque.harvestTools).length > 0
}

function puedeCosechar (bloque) {
  if (!exigeHerramienta(bloque)) return true
  return bot.inventory.items().some((it) => bloque.canHarvest(it.type))
}

function herramientasQueSirven (bloque) {
  return Object.keys(bloque.harvestTools || {})
    .map((id) => bot.registry.items[id] && bot.registry.items[id].name)
    .filter(Boolean)
    .join(' / ')
}

function itemsSueltos (cerca, radio) {
  return Object.values(bot.entities).filter((e) =>
    e && e.position && (e.name === 'item' || e.displayName === 'Item' || e.objectType === 'Item') &&
    e.position.distanceTo(cerca) < radio)
}

async function recogerDrops (cerca, radio = 8, espera = 600) {
  await dormir(espera)
  const intentados = new Set()
  for (let i = 0; i < 8; i++) {
    revisarCancelado()
    const item = itemsSueltos(cerca, radio)
      .filter((e) => !intentados.has(e.id))
      .sort((a, b) => a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position))[0]
    if (!item) return
    intentados.add(item.id)
    try {
      await irA(new GoalNear(item.position.x, item.position.y, item.position.z, 0), 8)
    } catch (e) {
      continue
    }
    await dormir(250)
  }
}

async function accionBuscarBloque ({ bloque, radio = 64 }) {
  const ids = bloquesPorNombre(bloque).map((b) => b.id)
  if (!ids.length) throw new ErrorAccion(`No conozco el bloque '${bloque}'. Usa el nombre interno en inglés (oak_log, iron_ore...).`)
  const pos = bot.findBlock({ matching: ids, maxDistance: Math.min(radio, 128) })
  if (!pos) return { ok: true, mensaje: `No hay ${bloque} en ${radio} bloques a la redonda. Explora hacia otro lado.`, datos: { encontrado: false } }
  return {
    ok: true,
    mensaje: `El ${bloque} más cercano está en ${posTxt(pos.position)} (a ${distancia(pos.position)} bloques).`,
    datos: { encontrado: true, x: pos.position.x, y: pos.position.y, z: pos.position.z }
  }
}

async function accionIrA ({ x, y, z, margen = 1 }) {
  await irA(new GoalNear(x, y, z, Math.max(0, margen)), 90)
  return { ok: true, mensaje: `Llegué cerca de ${x},${y},${z}.` }
}

async function accionIrABloque ({ bloque, radio = 64 }) {
  const ids = bloquesPorNombre(bloque).map((b) => b.id)
  if (!ids.length) throw new ErrorAccion(`No conozco el bloque '${bloque}'.`)
  const b = bot.findBlock({ matching: ids, maxDistance: Math.min(radio, 128) })
  if (!b) throw new ErrorAccion(`No hay ${bloque} en ${radio} bloques a la redonda.`)
  await irA(new GoalGetToBlock(b.position.x, b.position.y, b.position.z), 90)
  return { ok: true, mensaje: `Estoy junto a ${bloque} en ${posTxt(b.position)}.` }
}

const MAX_BAJAR = 8     // cuántos bloques por debajo de donde empezó puede llegar a cavar

function estaExpuesto (pos) {
  for (const v of VECINOS) {
    const b = bot.blockAt(pos.plus(v))
    if (b && b.boundingBox === 'empty' && b.name !== 'lava') return true
  }
  return false
}

function tieneLavaCerca (pos) {
  return VECINOS.some((v) => { const b = bot.blockAt(pos.plus(v)); return b && b.name === 'lava' })
}

// Menor puntaje = mejor. Prefiere bloques a la vista y cercanos, y castiga ir hacia abajo:
// así, tras picar uno, sigue con los vecinos del mismo nivel en vez de cavar una escalera.
function puntaje (pos) {
  const yo = bot.entity.position
  const bajada = Math.max(0, yo.y - pos.y)
  return yo.distanceTo(pos) + (estaExpuesto(pos) ? 0 : 6) + 2.5 * bajada
}

function alcanzaSinMoverse (bloque) {
  const ojos = bot.entity.position.offset(0, bot.entity.height || 1.62, 0)
  return ojos.distanceTo(bloque.position.offset(0.5, 0.5, 0.5)) <= 4.4 && bot.canSeeBlock(bloque)
}

async function accionRecolectar ({ bloque, cantidad = 1 }) {
  const objetivos = bloquesPorNombre(bloque)
  if (!objetivos.length) throw new ErrorAccion(`No conozco el bloque '${bloque}'. Usa el nombre interno en inglés.`)
  const ids = objetivos.map((b) => b.id)
  const ignorar = new Set()
  const antes = inventarioPlano()
  const yInicio = bot.entity.position.y
  let picados = 0
  let fallos = 0
  let muyHondos = 0
  cantidad = Math.max(1, Math.min(cantidad, 64))
  while (picados < cantidad && fallos < 4) {
    revisarCancelado()
    // findBlocks con lista de ids (un matcher-función no recibe la posición del bloque en todas las rutas)
    const todas = bot.findBlocks({ matching: ids, maxDistance: 48, count: 80 }).filter((p) => !ignorar.has(posTxt(p)))
    const utiles = todas.filter((p) => p.y >= yInicio - MAX_BAJAR && !tieneLavaCerca(p))
    muyHondos = todas.filter((p) => p.y < yInicio - MAX_BAJAR).length
    utiles.sort((a, b) => puntaje(a) - puntaje(b))
    const objetivo = utiles.length ? bot.blockAt(utiles[0]) : null
    if (!objetivo) {
      if (picados === 0) {
        if (muyHondos) throw new ErrorAccion(`Los ${bloque} que hay están a más de ${MAX_BAJAR} bloques bajo mí y cavar tan hondo es arriesgado (lava). ` +
          'Busca una ladera o cueva donde se vean a la vista (ir_a hacia otro lado).')
        throw new ErrorAccion(`No hay ${bloque} a la vista en 48 bloques. Explora con ir_a hacia otro lado.`)
      }
      break
    }
    if (!puedeCosechar(objetivo)) {
      throw new ErrorAccion(`No puedo picar ${objetivo.name} con lo que tengo: necesitas ${herramientasQueSirven(objetivo)} en el inventario.`)
    }
    try {
      if (!alcanzaSinMoverse(objetivo)) {
        await irA(new GoalGetToBlock(objetivo.position.x, objetivo.position.y, objetivo.position.z), 45)
      }
      const actual = bot.blockAt(objetivo.position)
      if (!actual || !ids.includes(actual.type)) { ignorar.add(posTxt(objetivo.position)); continue }
      await equiparMejorHerramienta(actual)
      await bot.dig(actual)
      picados++
      await recogerDrops(objetivo.position, 6, 350)
    } catch (e) {
      if (cancelado) throw new ErrorAccion('Acción cancelada por el usuario.')
      ignorar.add(posTxt(objetivo.position))
      fallos++
    }
  }
  await recogerDrops(bot.entity.position, 10, 900)   // barrido final: lo que haya quedado tirado cerca
  const despues = inventarioPlano()
  const ganado = []
  for (const [k, v] of Object.entries(despues)) if (v > (antes[k] || 0)) ganado.push(`${k} +${v - (antes[k] || 0)}`)
  if (picados === 0) throw new ErrorAccion(`No logré picar ${bloque} (no pude llegar a los bloques cercanos).`)
  const bajo = Math.round(yInicio - bot.entity.position.y)
  return {
    ok: true,
    mensaje: `Piqué ${picados} bloque(s) de ${bloque}` + (picados < cantidad ? ` (pedías ${cantidad}; no quedan más a mano sin cavar muy hondo)` : '') +
      `. Ahora tengo: ${ganado.join(', ') || 'nada nuevo (¿se perdieron los drops?)'}.` +
      (bajo >= 3 ? ` Ojo: terminé ${bajo} bloques más abajo de donde empecé.` : ''),
    datos: { picados, ganado }
  }
}

function diagnosticoCraft (nombre, item) {
  const todas = recipe.find(item.id, null)
  if (!todas.length) return `No existe una receta para fabricar ${nombre}.`
  let mejor = null
  for (const r of todas) {
    const faltan = []
    for (const d of r.delta) {
      if (d.count >= 0) continue
      const tengo = bot.inventory.count(d.id, d.metadata)
      if (tengo < -d.count) faltan.push(`${-d.count - tengo} más de ${bot.registry.items[d.id].name}`)
    }
    if (!mejor || faltan.length < mejor.faltan.length) mejor = { r, faltan }
  }
  const mesa = mejor.r.requiresTable ? ' Esta receta necesita una crafting_table cerca.' : ''
  return `No puedo fabricar ${nombre}: te faltan ${mejor.faltan.join(', ') || 'materiales'}.${mesa}`
}

async function accionCraftear ({ item, cantidad = 1 }) {
  const candidatos = itemsPorNombre(item)
  if (!candidatos.length) throw new ErrorAccion(`No conozco el item '${item}'. Usa el nombre interno en inglés (planks, stick, wooden_pickaxe...).`)
  cantidad = Math.max(1, Math.min(cantidad, 64))
  const idMesa = bot.registry.blocksByName.crafting_table.id
  // 1) recetas que no necesitan mesa; 2) recetas con mesa si hay una cerca
  for (const it of candidatos) {
    const sinMesa = bot.recipesFor(it.id, null, cantidad, null)[0]
    if (sinMesa) {
      const veces = Math.ceil(cantidad / sinMesa.result.count)
      await bot.craft(sinMesa, veces, null)
      return { ok: true, mensaje: `Fabriqué ${veces * sinMesa.result.count} de ${it.name}.`, datos: { item: it.name } }
    }
  }
  const mesa = bot.findBlock({ matching: idMesa, maxDistance: 32 })
  for (const it of candidatos) {
    if (!mesa) break
    const conMesa = bot.recipesFor(it.id, null, cantidad, mesa)[0]
    if (conMesa) {
      if (bot.entity.position.distanceTo(mesa.position) > 3.5) {
        await irA(new GoalNear(mesa.position.x, mesa.position.y, mesa.position.z, 2), 45)
      }
      const veces = Math.ceil(cantidad / conMesa.result.count)
      await bot.craft(conMesa, veces, mesa)
      return { ok: true, mensaje: `Fabriqué ${veces * conMesa.result.count} de ${it.name} usando la crafting_table.`, datos: { item: it.name } }
    }
  }
  // falló: explicar por qué
  const principal = candidatos[0]
  const necesitaMesa = recipe.find(principal.id, null).every((r) => r.requiresTable)
  if (necesitaMesa && !mesa) {
    const tengoMesa = itemEnInventario('crafting_table')
    throw new ErrorAccion(`${principal.name} se fabrica en una crafting_table y no hay ninguna a 32 bloques. ` +
      (tengoMesa ? 'Tienes una en el inventario: colócala con la herramienta colocar y vuelve a intentar.'
        : 'Fabrica una (4 planks) y colócala con colocar.'))
  }
  throw new ErrorAccion(diagnosticoCraft(item, principal))
}

const VECINOS = [new Vec3(0, -1, 0), new Vec3(1, 0, 0), new Vec3(-1, 0, 0), new Vec3(0, 0, 1), new Vec3(0, 0, -1), new Vec3(0, 1, 0)]

function puntoLibreCerca () {
  const base = bot.entity.position.floored()
  for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1], [2, 0], [-2, 0], [0, 2], [0, -2]]) {
    const p = base.offset(dx, 0, dz)
    const aqui = bot.blockAt(p)
    const suelo = bot.blockAt(p.offset(0, -1, 0))
    if (aqui && aqui.name === 'air' && suelo && suelo.boundingBox === 'block') return p
  }
  return null
}

async function accionColocar ({ bloque, x, y, z }) {
  const it = itemEnInventario(bloque)
  if (!it) throw new ErrorAccion(`No tienes ${bloque} en el inventario.`)
  let destino
  if (x !== undefined && y !== undefined && z !== undefined) destino = new Vec3(x, y, z)
  else {
    destino = puntoLibreCerca()
    if (!destino) throw new ErrorAccion('No encuentro un lugar libre junto a mí para colocarlo. Muévete a un sitio más despejado.')
  }
  if (bot.entity.position.distanceTo(destino) > 4) await irA(new GoalNear(destino.x, destino.y, destino.z, 3), 45)
  const objetivo = bot.blockAt(destino)
  if (objetivo && objetivo.name !== 'air' && objetivo.boundingBox === 'block') throw new ErrorAccion(`En ${posTxt(destino)} ya hay ${objetivo.name}.`)
  const yo = bot.entity.position.floored()
  if (destino.equals(yo) || destino.equals(yo.offset(0, 1, 0))) throw new ErrorAccion('Ese lugar es donde estoy parado; elige otro.')
  for (const v of VECINOS) {
    const ref = bot.blockAt(destino.plus(v))
    if (ref && ref.boundingBox === 'block') {
      await bot.equip(it, 'hand')
      await bot.lookAt(ref.position.offset(0.5, 0.5, 0.5))
      await bot.placeBlock(ref, v.scaled(-1))
      return { ok: true, mensaje: `Coloqué ${it.name} en ${posTxt(destino)}.`, datos: { x: destino.x, y: destino.y, z: destino.z } }
    }
  }
  throw new ErrorAccion(`No hay ningún bloque sólido junto a ${posTxt(destino)} donde apoyarlo.`)
}

async function accionEquipar ({ item, destino = 'hand' }) {
  const it = itemEnInventario(item)
  if (!it) throw new ErrorAccion(`No tienes ${item} en el inventario.`)
  await bot.equip(it, destino)
  return { ok: true, mensaje: `Equipé ${it.name} en ${destino}.` }
}

const HOSTILES = new Set(['zombie', 'skeleton', 'creeper', 'spider', 'cave_spider', 'enderman', 'witch', 'slime', 'drowned', 'husk',
  'stray', 'phantom', 'pillager', 'vindicator', 'blaze', 'ghast', 'hoglin', 'zoglin', 'wither_skeleton', 'silverfish', 'endermite',
  'guardian', 'shulker', 'vex', 'ravager', 'evoker', 'magma_cube', 'zombie_villager', 'piglin_brute', 'warden'])

function esHostil (e) {
  return HOSTILES.has(e.name) || e.kind === 'Hostile mobs'
}

async function accionAtacar ({ entidad, cantidad = 1 }) {
  const nombre = limpiarNombre(entidad)
  const espadas = bot.inventory.items().filter((i) => /_sword$|_axe$/.test(i.name))
  const orden = ['netherite', 'diamond', 'iron', 'stone', 'golden', 'wooden']
  espadas.sort((a, b) => orden.findIndex((m) => a.name.startsWith(m)) - orden.findIndex((m) => b.name.startsWith(m)) || (b.name.endsWith('sword') ? 1 : -1))
  if (espadas[0]) await bot.equip(espadas[0], 'hand')
  let derrotados = 0
  const inicio = Date.now()
  while (derrotados < cantidad && Date.now() - inicio < 60000) {
    revisarCancelado()
    const objetivo = bot.nearestEntity((e) => (e.name === nombre || (e.displayName || '').toLowerCase() === nombre) && e.position.distanceTo(bot.entity.position) < 48)
    if (!objetivo) break
    const t0 = Date.now()
    while (objetivo.isValid !== false && bot.entities[objetivo.id] && Date.now() - t0 < 25000) {
      revisarCancelado()
      if (bot.health < 5) throw new ErrorAccion(`Me retiro: me queda muy poca vida (${bot.health}).`)
      if (objetivo.position.distanceTo(bot.entity.position) > 3) {
        try { await irA(new GoalNear(objetivo.position.x, objetivo.position.y, objetivo.position.z, 2), 8) } catch (e) { /* sigue intentando */ }
      }
      await bot.lookAt(objetivo.position.offset(0, (objetivo.height || 1.6) * 0.8, 0))
      if (objetivo.position.distanceTo(bot.entity.position) < 4.2) bot.attack(objetivo)
      await dormir(650)
    }
    if (objetivo.isValid === false || !bot.entities[objetivo.id]) derrotados++
    else break
  }
  if (!derrotados) throw new ErrorAccion(`No logré derrotar a ningún ${entidad} (no hay cerca o no pude alcanzarlo).`)
  await recogerDrops(bot.entity.position)
  return { ok: true, mensaje: `Derroté ${derrotados} ${entidad}(s).`, datos: { derrotados } }
}

async function accionComer () {
  if (bot.food >= 20) return { ok: true, mensaje: 'No tengo hambre (20/20).' }
  const comidas = bot.inventory.items().filter((i) => bot.registry.foodsByName[i.name])
  if (!comidas.length) throw new ErrorAccion('No tengo comida en el inventario. Consigue carne (atacar cow/pig/chicken) o manzanas/pan.')
  comidas.sort((a, b) => bot.registry.foodsByName[b.name].foodPoints - bot.registry.foodsByName[a.name].foodPoints)
  await bot.equip(comidas[0], 'hand')
  await bot.consume()
  return { ok: true, mensaje: `Comí ${comidas[0].name}. Hambre: ${bot.food}/20.` }
}

async function accionDormir () {
  const cama = bot.findBlock({ matching: (b) => bot.isABed(b), maxDistance: 32 })
  if (!cama) throw new ErrorAccion('No hay ninguna cama a 32 bloques. Fabrica una (3 wool + 3 planks) y colócala.')
  await irA(new GoalNear(cama.position.x, cama.position.y, cama.position.z, 2), 45)
  try {
    await bot.sleep(cama)
  } catch (e) {
    throw new ErrorAccion('No pude dormir: ' + (e.message || e) + ' (solo se puede dormir de noche o con tormenta).')
  }
  const inicio = Date.now()
  while (bot.isSleeping && Date.now() - inicio < 60000) { revisarCancelado(); await dormir(500) }
  return { ok: true, mensaje: 'Dormí y ya amaneció.' }
}

async function accionAlejarse ({ distancia: dist = 20 }) {
  const hostiles = Object.values(bot.entities).filter((e) => e !== bot.entity && esHostil(e) && e.position.distanceTo(bot.entity.position) < 24)
  const yo = bot.entity.position
  let dx = Math.random() - 0.5
  let dz = Math.random() - 0.5
  if (hostiles.length) {
    dx = hostiles.reduce((s, e) => s + (yo.x - e.position.x), 0) / hostiles.length
    dz = hostiles.reduce((s, e) => s + (yo.z - e.position.z), 0) / hostiles.length
  }
  const largo = Math.hypot(dx, dz) || 1
  const d = Math.max(5, Math.min(dist, 60))
  await irA(new GoalNear(yo.x + (dx / largo) * d, yo.y, yo.z + (dz / largo) * d, 3), 20)
  return { ok: true, mensaje: hostiles.length ? `Me alejé de ${hostiles.length} enemigo(s).` : 'Me moví a otro lugar.' }
}

async function accionSubirASuperficie () {
  const yo = bot.entity.position.floored()
  const minY = (bot.game && bot.game.minY) || -64
  const maxY = ((bot.game && bot.game.height) || 384) + minY - 1
  let techo = null
  for (let y = maxY; y > yo.y; y--) {
    const b = bot.blockAt(new Vec3(yo.x, y, yo.z))
    if (!b || b.name === 'air' || b.name === 'cave_air' || b.name === 'void_air' || b.name.endsWith('_leaves') || b.boundingBox === 'empty') continue
    techo = y
    break
  }
  if (techo === null) return { ok: true, mensaje: 'Ya estoy en la superficie (hay cielo libre encima).' }
  await irA(new GoalNear(yo.x, techo + 1, yo.z, 1), 60)
  const p = bot.entity.position
  return { ok: true, mensaje: `Subí a la superficie: ahora estoy en ${posTxt(p)}.`, datos: { x: Math.floor(p.x), y: Math.floor(p.y), z: Math.floor(p.z) } }
}

async function accionEsperar ({ segundos }) {
  const s = Math.max(1, Math.min(Number(segundos) || 1, 30))
  for (let i = 0; i < s * 4; i++) { revisarCancelado(); await dormir(250) }
  return { ok: true, mensaje: `Esperé ${s} s.` }
}

async function accionDecir ({ mensaje }) {
  const m = String(mensaje || '').trim()
  if (!m) throw new ErrorAccion('El mensaje está vacío.')
  if (m.startsWith('/')) throw new ErrorAccion('Los comandos del juego (/...) están bloqueados por seguridad.')
  bot.chat(m.slice(0, 200))
  return { ok: true, mensaje: 'Mensaje enviado al chat.' }
}

const ACCIONES = {
  buscar_bloque: accionBuscarBloque,
  ir_a: accionIrA,
  ir_a_bloque: accionIrABloque,
  recolectar: accionRecolectar,
  craftear: accionCraftear,
  colocar: accionColocar,
  equipar: accionEquipar,
  atacar: accionAtacar,
  comer: accionComer,
  dormir: accionDormir,
  alejarse: accionAlejarse,
  subir_a_superficie: accionSubirASuperficie,
  esperar: accionEsperar,
  decir: accionDecir
}

// ---------------------------------------------------------------------------
// Estado
// ---------------------------------------------------------------------------
const INTERES = /(_log$|_ore$|^lava$|crafting_table|furnace|chest|_bed$|^coal_block|obsidian|spawner|_planks$)/
let idsInteresCache = null

function idsInteres () {
  if (!idsInteresCache) {
    idsInteresCache = Object.values(bot.registry.blocksByName).filter((b) => INTERES.test(b.name)).map((b) => b.id)
  }
  return idsInteresCache
}

// Solo busca bloques "útiles" por id (rápido: salta secciones enteras sin ninguno) en lugar de recorrer todo el volumen.
function escanear () {
  const yo = bot.entity.position
  const posiciones = bot.findBlocks({ matching: idsInteres(), maxDistance: 24, count: 400 })
  const agrupado = {}
  for (const p of posiciones) {
    const b = bot.blockAt(p)
    if (!b) continue
    const d = yo.distanceTo(p)
    const g = agrupado[b.name] || (agrupado[b.name] = { nombre: b.name, cantidad: 0, distancia: Infinity, x: 0, y: 0, z: 0 })
    g.cantidad++
    if (d < g.distancia) { g.distancia = Math.round(d * 10) / 10; g.x = p.x; g.y = p.y; g.z = p.z }
  }
  return Object.values(agrupado).sort((a, b) => a.distancia - b.distancia).slice(0, 12)
}

function estado (ligero) {
  if (!bot || !bot.entity) return { ok: false, mensaje: 'El bot no está conectado a ningún mundo.' }
  const base = { ok: true, inventario: inventarioPlano() }
  if (ligero) return base
  const yo = bot.entity.position
  const entidades = Object.values(bot.entities)
    .filter((e) => e !== bot.entity && e.name && e.position.distanceTo(yo) < 24 && e.name !== 'item' && e.type !== 'orb')
    .sort((a, b) => a.position.distanceTo(yo) - b.position.distanceTo(yo))
    .slice(0, 8)
    .map((e) => ({
      nombre: e.type === 'player' ? `${e.username || e.name} (jugador amigo)` : (e.username || e.name),
      distancia: Math.round(e.position.distanceTo(yo) * 10) / 10,
      hostil: e.type === 'player' ? false : esHostil(e)
    }))
  return Object.assign(base, {
    posicion: { x: Math.floor(yo.x), y: Math.floor(yo.y), z: Math.floor(yo.z) },
    dimension: bot.game && bot.game.dimension,
    es_dia: bot.time ? bot.time.isDay : null,
    vida: Math.round(bot.health),
    hambre: bot.food,
    mano: bot.heldItem ? bot.heldItem.name : null,
    bajo_los_pies: (() => { const b = bot.blockAt(yo.offset(0, -1, 0)); return b ? b.name : null })(),
    bloques: (() => { try { return escanear() } catch (e) { console.error('escanear falló:', e && e.message); return [] } })(),
    entidades,
    eventos: eventos.slice()
  })
}

// ---------------------------------------------------------------------------
// Conexión
// ---------------------------------------------------------------------------
function desconectar () {
  if (bot) {
    try { bot.removeAllListeners(); bot.quit() } catch (e) { /* ya estaba cerrado */ }
    bot = null
  }
}

function conectar ({ host, puerto, usuario, version, auth }) {
  desconectar()
  return new Promise((resolve) => {
    const opciones = { host: host || 'localhost', port: parseInt(puerto, 10) || 25565, username: usuario || 'Arche', auth: auth || 'offline' }
    if (version) opciones.version = String(version)
    let terminado = false
    const fin = (r) => { if (!terminado) { terminado = true; clearTimeout(t); resolve(r) } }
    const t = setTimeout(() => fin({ ok: false, mensaje: 'No pude entrar al mundo en 60 s. ¿Está abierto a LAN o el servidor encendido? ¿Es correcto el puerto?' }), 60000)
    let b
    try {
      b = mineflayer.createBot(opciones)
    } catch (e) {
      return fin({ ok: false, mensaje: 'No pude crear el bot: ' + (e.message || e) })
    }
    bot = b
    b.loadPlugin(pathfinder)
    b.once('spawn', async () => {
      idsInteresCache = null
      recipe = require('prismarine-recipe')(b.registry).Recipe
      movimientos = new Movements(b)
      movimientos.allowSprinting = true
      evento('Entré al mundo.')
      try { await Promise.race([b.waitForChunksToLoad(), dormir(10000)]) } catch (e) { /* seguimos igual */ }
      fin({ ok: true, mensaje: `Conectado como ${b.username} en ${opciones.host}:${opciones.port} (versión ${b.version}).` })
    })
    b.on('death', () => evento('Morí y reaparecí. Perdí lo que llevaba encima.'))
    let vidaPrevia = 20
    b.on('health', () => {
      if (b.health < vidaPrevia - 1) evento(`Recibí daño (vida ${Math.round(b.health)}).`)
      vidaPrevia = b.health
    })
    b.on('kicked', (razon) => { evento('Me expulsaron: ' + String(razon).slice(0, 80)); fin({ ok: false, mensaje: 'El servidor me expulsó: ' + String(razon).slice(0, 120) }) })
    b.on('error', (e) => fin({ ok: false, mensaje: 'Error de conexión: ' + (e.message || e) }))
    b.on('end', () => { evento('Se cerró la conexión.'); fin({ ok: false, mensaje: 'Se cerró la conexión antes de entrar.' }) })
    b.on('messagestr', (m) => { if (m && !m.includes(b.username)) evento('Chat: ' + m.slice(0, 80)) })
  })
}

// ---------------------------------------------------------------------------
// Servidor HTTP (solo local)
// ---------------------------------------------------------------------------
function responder (res, codigo, cuerpo) {
  const datos = JSON.stringify(cuerpo)
  res.writeHead(codigo, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(datos) })
  res.end(datos)
}

function leerCuerpo (req) {
  return new Promise((resolve) => {
    let texto = ''
    req.on('data', (c) => { texto += c; if (texto.length > 1e6) req.destroy() })
    req.on('end', () => { try { resolve(texto ? JSON.parse(texto) : {}) } catch (e) { resolve({}) } })
  })
}

async function ejecutarAccion ({ nombre, args }) {
  if (!bot || !bot.entity) return { ok: false, mensaje: 'El bot no está conectado a ningún mundo.' }
  const fn = ACCIONES[nombre]
  if (!fn) return { ok: false, mensaje: `Acción desconocida: ${nombre}.` }
  if (ocupado) return { ok: false, mensaje: 'Todavía estoy ocupado con otra acción.' }
  ocupado = true
  cancelado = false
  try {
    return await fn(args || {})
  } catch (e) {
    if (e instanceof ErrorAccion) return { ok: false, mensaje: e.message }
    return { ok: false, mensaje: `Falló ${nombre}: ${e.message || e}` }
  } finally {
    ocupado = false
    try { bot.clearControlStates() } catch (e) { /* sin bot */ }
  }
}

// Lo que el propio juego sabe: recetas y qué herramienta pide cada bloque. Sirve para planear SIN ningún modelo de IA.
function conocimiento (version) {
  const v = (bot && bot.version) || version
  if (!v) return { ok: false, mensaje: 'No sé de qué versión de Minecraft hablar: conéctate al mundo o pasa la versión.' }
  let md
  try { md = require('minecraft-data')(v) } catch (e) { md = null }
  if (!md) return { ok: false, mensaje: `No tengo datos para la versión ${v}.` }
  const nombre = (id) => (md.items[id] ? md.items[id].name : null)
  const idDe = (x) => (x !== null && typeof x === 'object' ? x.id : x)
  const recetas = {}
  for (const [id, lista] of Object.entries(md.recipes || {})) {
    const res = nombre(Number(id))
    if (!res) continue
    recetas[res] = lista.map((r) => {
      const ing = {}
      const sumar = (x) => {
        if (x === null || x === undefined || x === -1) return
        const n = nombre(idDe(x))
        if (n) ing[n] = (ing[n] || 0) + ((typeof x === 'object' && x.count) || 1)
      }
      let mesa = false
      if (r.inShape) { r.inShape.forEach((f) => f.forEach(sumar)); mesa = r.inShape.length > 2 || r.inShape.some((f) => f.length > 2) }
      else if (r.ingredients) { r.ingredients.forEach(sumar); mesa = r.ingredients.length > 4 }
      return { ing, sal: (r.result && r.result.count) || 1, mesa }
    })
  }
  const bloques = {}
  for (const b of md.blocksArray) {
    if (!b.diggable) continue
    const herr = b.harvestTools ? Object.keys(b.harvestTools).map((i) => nombre(Number(i))).filter(Boolean) : null
    const suelta = (b.drops || []).map((d) => nombre(idDe(d && d.drop !== undefined ? d.drop : d))).filter(Boolean)
    bloques[b.name] = { dureza: b.hardness, herr, suelta }
  }
  return { ok: true, version: v, recetas, bloques }
}

const servidor = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  try {
    if (req.method === 'GET' && url.pathname === '/ping') return responder(res, 200, { ok: true, conectado: !!(bot && bot.entity) })
    if (req.method === 'GET' && url.pathname === '/estado') {
      const t0 = Date.now()
      const e = estado(url.searchParams.get('ligero') === '1')
      if (Date.now() - t0 > 1500) console.error(`estado lento: ${Date.now() - t0} ms`)
      return responder(res, e.ok ? 200 : 409, e)
    }
    if (req.method === 'GET' && url.pathname === '/datos') return responder(res, 200, conocimiento(url.searchParams.get('version') || ''))
    if (req.method === 'POST' && url.pathname === '/conectar') return responder(res, 200, await conectar(await leerCuerpo(req)))
    if (req.method === 'POST' && url.pathname === '/accion') return responder(res, 200, await ejecutarAccion(await leerCuerpo(req)))
    if (req.method === 'POST' && url.pathname === '/detener') {
      cancelado = true
      if (bot && bot.pathfinder) bot.pathfinder.stop()
      if (bot) { try { bot.clearControlStates() } catch (e) { /* nada */ } }
      return responder(res, 200, { ok: true, mensaje: 'Detenido.' })
    }
    if (req.method === 'POST' && url.pathname === '/desconectar') { desconectar(); return responder(res, 200, { ok: true }) }
    return responder(res, 404, { ok: false, mensaje: 'Ruta desconocida.' })
  } catch (e) {
    return responder(res, 500, { ok: false, mensaje: 'Error interno del puente: ' + (e.message || e) })
  }
})

servidor.listen(PUERTO, '127.0.0.1', () => {
  console.log(`Puente de Minecraft escuchando en 127.0.0.1:${PUERTO}`)
})

process.on('uncaughtException', (e) => { console.error('Excepción no atrapada:', e && e.stack ? e.stack : e) })
process.on('unhandledRejection', (e) => { console.error('Promesa rechazada:', e && e.stack ? e.stack : e) })
process.on('SIGTERM', () => { desconectar(); process.exit(0) })
