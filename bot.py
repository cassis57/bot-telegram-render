import json
import datetime
import logging
import os
from threading import Thread
import asyncio
import urllib.parse

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

DATA_FILE = 'data.json'

def load_data():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"cuentas": [], "clientes": {}, "ganancias": {}}

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def crear_boton_whatsapp(numero, mensaje):
    texto_url = urllib.parse.quote(mensaje)
    url = f"https://wa.me/{numero}?text={texto_url}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📲 WhatsApp Cliente", url=url)]])
    return keyboard

async def comandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = """*** COMANDOS PRINCIPALES ***

/comandos - Mostrar comandos
/basecc - Mostrar todas las cuentas completas
/agregarcc (plataforma) (correo contraseña) / (correo contraseña) / ... - Agregar cuentas múltiples
/comprarcc (número_cliente) (plataforma) (fecha_vencimiento) (ganancia_entera) - Comprar cuenta con ganancia
/asignarcc (plataforma) (correo) (número_cliente) (fecha_vencimiento) - Asignar cuenta disponible a cliente con fecha
/info (número_cliente) - Info compras cliente
/renovar (número_cliente) (plataforma) (correo) (fecha_vencimiento) - Renovar servicio
/reemplazar (plataforma) (correo_viejo) (correo_nuevo) (contraseña_nueva) - Reemplazar cuenta
/vencidos - Listar cuentas vencidas, liberar y sincronizar base
/eliminar (plataforma) (correo) - Eliminar cuenta
/sincronizar - Sincronizar bases clientes y cuentas
/estadisticas - Mostrar resumen de estadísticas
/buscarcc (correo_o_plataforma) - Buscar cuentas por correo o plataforma
/cancelarcompra (número_cliente) (plataforma) (correo) - Cancelar compra (liberar cuenta)
"""
    await update.message.reply_text(texto)

async def basecc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    cuentas = data["cuentas"]
    if not cuentas:
        await update.message.reply_text("No hay cuentas registradas aún.")
        return

    plataformas = {}
    for c in cuentas:
        plataforma = c["plataforma"].upper()
        if plataforma not in plataformas:
            plataformas[plataforma] = []
        plataformas[plataforma].append(c)

    texto = ""
    for plataforma, cuentas_plat in plataformas.items():
        texto += f"-- ({plataforma}) -- ({len(cuentas_plat)})\n"
        for c in cuentas_plat:
            estado = "Vendido" if c["estado"] == "vendido" else "Disponible"
            cliente = c["cliente"] if c["cliente"] else "Libre"
            fecha = c["fecha_vencimiento"] if c["fecha_vencimiento"] else ""
            texto += f"- {c['correo']}  /  {estado}\n{cliente}  /  {fecha}\n"
        texto += "\n"

    await update.message.reply_text(texto.strip())

async def agregarcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso correcto:\n/agregarcc (plataforma) (correo contraseña) / (correo contraseña) / ...")
        return

    plataforma = args[0].strip()
    cuentas_texto = update.message.text.split(' ', 2)[2].strip()
    cuentas_partes = [c.strip() for c in cuentas_texto.split(' / ') if c.strip()]

    cuentas_agregadas = 0
    mensajes_error = []

    for cuenta_str in cuentas_partes:
        partes = cuenta_str.split()
        if len(partes) < 2:
            mensajes_error.append(f"Formato incorrecto en cuenta: '{cuenta_str}'")
            continue
        correo = partes[0].strip()
        contraseña = ' '.join(partes[1:]).strip()

        existe = any(c["plataforma"].lower() == plataforma.lower() and c["correo"].lower() == correo.lower() for c in data["cuentas"])
        if existe:
            mensajes_error.append(f"La cuenta {correo} ya está registrada.")
            continue

        nueva_cuenta = {
            "plataforma": plataforma,
            "correo": correo,
            "contraseña": contraseña,
            "estado": "disponible",
            "cliente": None,
            "fecha_vencimiento": ""
        }
        data["cuentas"].append(nueva_cuenta)
        cuentas_agregadas += 1

    save_data(data)

    mensaje_respuesta = f"✅ Se agregaron {cuentas_agregadas} cuentas a {plataforma}.\n"
    if mensajes_error:
        mensaje_respuesta += "⚠️ Algunos errores:\n" + "\n".join(mensajes_error)

    await update.message.reply_text(mensaje_respuesta)

async def comprarcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args

    if len(args) < 4:
        await update.message.reply_text("Uso correcto:\n/comprarcc (número_cliente) (plataforma) (fecha_vencimiento) (ganancia)")
        return

    ganancia_str = args[-1]
    fecha_vencimiento = args[-2]
    plataforma = args[-3]
    numero_cliente_parts = args[:-3]
    numero_cliente = ' '.join(numero_cliente_parts).strip()

    if not ganancia_str.isdigit():
        await update.message.reply_text("Ganancia inválida, debe ser un número entero positivo sin decimales.")
        return

    ganancia = int(ganancia_str)

    cuenta_encontrada = None
    for c in data["cuentas"]:
        if c["plataforma"].lower() == plataforma.lower() and c["estado"] == "disponible":
            cuenta_encontrada = c
            break

    if not cuenta_encontrada:
        await update.message.reply_text("No hay cuentas disponibles para esa plataforma.")
        return

    correo_cuenta = cuenta_encontrada["correo"].lower()
    plataforma_cuenta = plataforma.lower()
    clientes_a_modificar = []
    for cliente_num, compras in list(data["clientes"].items()):
        nuevas_compras = [compra for compra in compras
                         if not (compra["correo"].lower() == correo_cuenta and compra["plataforma"].lower() == plataforma_cuenta)]
        if len(nuevas_compras) != len(compras):
            data["clientes"][cliente_num] = nuevas_compras
            clientes_a_modificar.append(cliente_num)

    for cliente_num in clientes_a_modificar:
        if len(data["clientes"][cliente_num]) == 0:
            del data["clientes"][cliente_num]

    cuenta_encontrada["estado"] = "vendido"
    cuenta_encontrada["cliente"] = numero_cliente
    cuenta_encontrada["fecha_vencimiento"] = fecha_vencimiento

    if numero_cliente not in data["clientes"]:
        data["clientes"][numero_cliente] = []

    existe = False
    for compra in data["clientes"][numero_cliente]:
        if compra["plataforma"].lower() == plataforma_cuenta and compra["correo"].lower() == correo_cuenta:
            compra["fecha_vencimiento"] = fecha_vencimiento
            existe = True
            break
    if not existe:
        data["clientes"][numero_cliente].append({
            "plataforma": plataforma,
            "correo": cuenta_encontrada["correo"],
            "contraseña": cuenta_encontrada["contraseña"],
            "fecha_vencimiento": fecha_vencimiento
        })

    if "ganancias" not in data:
        data["ganancias"] = {}
    ganancia_actual = data["ganancias"].get(plataforma.lower(), 0)
    data["ganancias"][plataforma.lower()] = ganancia_actual + ganancia

    save_data(data)

    mensaje = f"""- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
-- *{plataforma.upper()}* --

correo: {cuenta_encontrada['correo']}
contraseña: {cuenta_encontrada['contraseña']}
*Toca renovar:* {fecha_vencimiento}
"""

    boton = crear_boton_whatsapp(numero_cliente, mensaje)
    await update.message.reply_text(mensaje, parse_mode='Markdown', reply_markup=boton)

# (Continúa con las otras funciones sin cambiar nada, solo asegurándote que la indentación sea correcta)
import asyncio

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

DATA_FILE = 'data.json'

def load_data():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"cuentas": [], "clientes": {}, "ganancias": {}}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def crear_boton_whatsapp(numero, mensaje):
    texto_url = mensaje.replace('\n', '%0A').replace(' ', '%20').replace('*', '')
    url = f"https://wa.me/{numero}?text={texto_url}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📲 WhatsApp Cliente", url=url)]])
    return keyboard

async def comandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = """*** COMANDOS PRINCIPALES ***

/comandos - Mostrar comandos
/basecc - Mostrar todas las cuentas completas
/agregarcc (plataforma) (correo contraseña) / (correo contraseña) / ... - Agregar cuentas múltiples
/comprarcc (número_cliente) (plataforma) (fecha_vencimiento) (ganancia_entera) - Comprar cuenta con ganancia
/asignarcc (plataforma) (correo) (número_cliente) (fecha_vencimiento) - Asignar cuenta disponible a cliente con fecha
/info (número_cliente) - Info compras cliente
/renovar (número_cliente) (plataforma) (correo) (fecha_vencimiento) - Renovar servicio
/reemplazar (plataforma) (correo_viejo) (correo_nuevo) (contraseña_nueva) - Reemplazar cuenta
/vencidos - Listar cuentas vencidas, liberar y sincronizar base
/eliminar (plataforma) (correo) - Eliminar cuenta
/sincronizar - Sincronizar bases clientes y cuentas
/estadisticas - Mostrar resumen de estadísticas
/buscarcc (correo_o_plataforma) - Buscar cuentas por correo o plataforma
/cancelarcompra (número_cliente) (plataforma) (correo) - Cancelar compra (liberar cuenta)
"""
    await update.message.reply_text(texto)
async def basecc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    cuentas = data["cuentas"]
    if not cuentas:
        await update.message.reply_text("No hay cuentas registradas aún.")
        return

    plataformas = {}
    for c in cuentas:
        plataforma = c["plataforma"].upper()
        if plataforma not in plataformas:
            plataformas[plataforma] = []
        plataformas[plataforma].append(c)

    texto = ""
    for plataforma, cuentas_plat in plataformas.items():
        texto += f"-- ({plataforma}) -- ({len(cuentas_plat)})\n"
        for c in cuentas_plat:
            estado = "Vendido" if c["estado"] == "vendido" else "Disponible"
            cliente = c["cliente"] if c["cliente"] else "Libre"
            fecha = c["fecha_vencimiento"] if c["fecha_vencimiento"] else ""
            texto += f"- {c['correo']}  /  {estado}\n{cliente}  /  {fecha}\n"
        texto += "\n"

    await update.message.reply_text(texto.strip())

async def agregarcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso correcto:\n/agregarcc (plataforma) (correo contraseña) / (correo contraseña) / ...")
        return

    plataforma = args[0].strip()
    cuentas_texto = update.message.text.split(' ', 2)[2].strip()
    cuentas_partes = [c.strip() for c in cuentas_texto.split(' / ') if c.strip()]

    cuentas_agregadas = 0
    mensajes_error = []

    for cuenta_str in cuentas_partes:
        partes = cuenta_str.split()
        if len(partes) < 2:
            mensajes_error.append(f"Formato incorrecto en cuenta: '{cuenta_str}'")
            continue
        correo = partes[0].strip()
        contraseña = ' '.join(partes[1:]).strip()

        existe = any(c["plataforma"].lower() == plataforma.lower() and c["correo"].lower() == correo.lower() for c in data["cuentas"])
        if existe:
            mensajes_error.append(f"La cuenta {correo} ya está registrada.")
            continue

        nueva_cuenta = {
            "plataforma": plataforma,
            "correo": correo,
            "contraseña": contraseña,
            "estado": "disponible",
            "cliente": None,
            "fecha_vencimiento": ""
        }
        data["cuentas"].append(nueva_cuenta)
        cuentas_agregadas += 1

    save_data(data)

    mensaje_respuesta = f"✅ Se agregaron {cuentas_agregadas} cuentas a {plataforma}.\n"
    if mensajes_error:
        mensaje_respuesta += "⚠️ Algunos errores:\n" + "\n".join(mensajes_error)

    await update.message.reply_text(mensaje_respuesta)

async def comprarcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args

    if len(args) < 4:
        await update.message.reply_text("Uso correcto:\n/comprarcc (número_cliente) (plataforma) (fecha_vencimiento) (ganancia)")
        return

    ganancia_str = args[-1]
    fecha_vencimiento = args[-2]
    plataforma = args[-3]
    numero_cliente_parts = args[:-3]
    numero_cliente = ' '.join(numero_cliente_parts).strip()

    if not ganancia_str.isdigit():
        await update.message.reply_text("Ganancia inválida, debe ser un número entero positivo sin decimales.")
        return

    ganancia = int(ganancia_str)

    cuenta_encontrada = None
async def comprarcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args

    if len(args) < 4:
        await update.message.reply_text("Uso correcto:\n/comprarcc (número_cliente) (plataforma) (fecha_vencimiento) (ganancia)")
        return

    ganancia_str = args[-1]
    fecha_vencimiento = args[-2]
    plataforma = args[-3]
    numero_cliente_parts = args[:-3]
    numero_cliente = ' '.join(numero_cliente_parts).strip()

    if not ganancia_str.isdigit():
        await update.message.reply_text("Ganancia inválida, debe ser un número entero positivo sin decimales.")
        return

    ganancia = int(ganancia_str)

    cuenta_encontrada = None
    for c in data["cuentas"]:
        if c["plataforma"].lower() == plataforma.lower() and c["estado"] == "disponible":
            cuenta_encontrada = c
            break

    if not cuenta_encontrada:
        await update.message.reply_text("No hay cuentas disponibles para esa plataforma.")
        return

    correo_cuenta = cuenta_encontrada["correo"].lower()
    plataforma_cuenta = plataforma.lower()
    clientes_a_modificar = []
    for cliente_num, compras in list(data["clientes"].items()):
        nuevas_compras = [compra for compra in compras
                         if not (compra["correo"].lower() == correo_cuenta and compra["plataforma"].lower() == plataforma_cuenta)]
        if len(nuevas_compras) != len(compras):
            data["clientes"][cliente_num] = nuevas_compras
            clientes_a_modificar.append(cliente_num)

    for cliente_num in clientes_a_modificar:
        if len(data["clientes"][cliente_num]) == 0:
            del data["clientes"][cliente_num]

    cuenta_encontrada["estado"] = "vendido"
    cuenta_encontrada["cliente"] = numero_cliente
    cuenta_encontrada["fecha_vencimiento"] = fecha_vencimiento

    if numero_cliente not in data["clientes"]:
        data["clientes"][numero_cliente] = []

    existe = False
    for compra in data["clientes"][numero_cliente]:
        if compra["plataforma"].lower() == plataforma_cuenta and compra["correo"].lower() == correo_cuenta:
            compra["fecha_vencimiento"] = fecha_vencimiento
            existe = True
            break
    if not existe:
        data["clientes"][numero_cliente].append({
            "plataforma": plataforma,
            "correo": cuenta_encontrada["correo"],
            "contraseña": cuenta_encontrada["contraseña"],
            "fecha_vencimiento": fecha_vencimiento
        })

    if "ganancias" not in data:
        data["ganancias"] = {}
    ganancia_actual = data["ganancias"].get(plataforma.lower(), 0)
    data["ganancias"][plataforma.lower()] = ganancia_actual + ganancia

    save_data(data)

    mensaje = f"""- - - - - - - - - - - - - - - -
-- *{plataforma.upper()}* --

correo: {cuenta_encontrada['correo']}
contraseña: {cuenta_encontrada['contraseña']}
*Toca renovar:* {fecha_vencimiento}
"""

    boton = crear_boton_whatsapp(numero_cliente, mensaje)
    await update.message.reply_text(mensaje, parse_mode='Markdown', reply_markup=boton)


    if len(args) < 4:
        await update.message.reply_text("Uso correcto:\n/comprarcc (número_cliente) (plataforma) (fecha_vencimiento) (ganancia)")
        return

    ganancia_str = args[-1]
    fecha_vencimiento = args[-2]
    plataforma = args[-3]
    numero_cliente_parts = args[:-3]
    numero_cliente = ' '.join(numero_cliente_parts).strip()

    if not ganancia_str.isdigit():
        await update.message.reply_text("Ganancia inválida, debe ser un número entero positivo sin decimales.")
        return

    ganancia = int(ganancia_str)

    cuenta_encontrada = None
    for c in data["cuentas"]:
        if c["plataforma"].lower() == plataforma.lower() and c["estado"] == "disponible":
            cuenta_encontrada = c
            break

    if not cuenta_encontrada:
        await update.message.reply_text("No hay cuentas disponibles para esa plataforma.")
        return

    correo_cuenta = cuenta_encontrada["correo"].lower()
    plataforma_cuenta = plataforma.lower()
    clientes_a_modificar = []
    for cliente_num, compras in list(data["clientes"].items()):
        nuevas_compras = [compra for compra in compras
                         if not (compra["correo"].lower() == correo_cuenta and compra["plataforma"].lower() == plataforma_cuenta)]
        if len(nuevas_compras) != len(compras):
            data["clientes"][cliente_num] = nuevas_compras
            clientes_a_modificar.append(cliente_num)

    for cliente_num in clientes_a_modificar:
        if len(data["clientes"][cliente_num]) == 0:
            del data["clientes"][cliente_num]

    cuenta_encontrada["estado"] = "vendido"
    cuenta_encontrada["cliente"] = numero_cliente
    cuenta_encontrada["fecha_vencimiento"] = fecha_vencimiento

    if numero_cliente not in data["clientes"]:
        data["clientes"][numero_cliente] = []

    existe = False
    for compra in data["clientes"][numero_cliente]:
        if compra["plataforma"].lower() == plataforma_cuenta and compra["correo"].lower() == correo_cuenta:
            compra["fecha_vencimiento"] = fecha_vencimiento
            existe = True
            break
    if not existe:
        data["clientes"][numero_cliente].append({
            "plataforma": plataforma,
            "correo": cuenta_encontrada["correo"],
            "contraseña": cuenta_encontrada["contraseña"],
            "fecha_vencimiento": fecha_vencimiento
        })

    if "ganancias" not in data:
        data["ganancias"] = {}

    ganancia_actual = data["ganancias"].get(plataforma.lower(), 0)
    data["ganancias"][plataforma.lower()] = ganancia_actual + ganancia

    save_data(data)

    mensaje = f"""- - - - - - - - - - - - - - - -
-- *{plataforma.upper()}* --

correo: {cuenta_encontrada['correo']}
contraseña: {cuenta_encontrada['contraseña']}
*Toca renovar:* {fecha_vencimiento}
"""

    boton = crear_boton_whatsapp(numero_cliente, mensaje)
    await update.message.reply_text(mensaje, parse_mode='Markdown', reply_markup=boton)


async def asignarcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args

    if len(args) < 4:
        await update.message.reply_text("Uso correcto:\n/asignarcc (plataforma) (correo) (número_cliente) (fecha_vencimiento)")
        return

    plataforma = args[0].strip()
    correo = args[1].strip()
    numero_cliente = args[2].strip()
    fecha_vencimiento = args[3].strip()

    cuenta_a_asignar = None
    for c in data["cuentas"]:
        if c["plataforma"].lower() == plataforma.lower() and c["correo"].lower() == correo.lower():
            cuenta_a_asignar = c
            break

    if not cuenta_a_asignar:
        await update.message.reply_text("No se encontró la cuenta especificada.")
        return

    if cuenta_a_asignar["estado"] != "disponible":
        await update.message.reply_text("La cuenta no está disponible para asignar.")
        return

    correo_cuenta = correo.lower()
    plataforma_cuenta = plataforma.lower()
    clientes_a_modificar = []
    for cliente_num, compras in list(data["clientes"].items()):
        nuevas_compras = [compra for compra in compras
                         if not (compra["correo"].lower() == correo_cuenta and compra["plataforma"].lower() == plataforma_cuenta)]
        if len(nuevas_compras) != len(compras):
            data["clientes"][cliente_num] = nuevas_compras
            clientes_a_modificar.append(cliente_num)
    for cliente_num in clientes_a_modificar:
        if len(data["clientes"][cliente_num]) == 0:
            del data["clientes"][cliente_num]

    cuenta_a_asignar["estado"] = "vendido"
    cuenta_a_asignar["cliente"] = numero_cliente
    cuenta_a_asignar["fecha_vencimiento"] = fecha_vencimiento

    if numero_cliente not in data["clientes"]:
        data["clientes"][numero_cliente] = []

    existe = False
    for compra in data["clientes"][numero_cliente]:
        if compra["plataforma"].lower() == plataforma_cuenta and compra["correo"].lower() == correo_cuenta:
            compra["fecha_vencimiento"] = fecha_vencimiento
            existe = True
            break
    if not existe:
        data["clientes"][numero_cliente].append({
            "plataforma": plataforma,
            "correo": correo,
            "contraseña": cuenta_a_asignar["contraseña"],
            "fecha_vencimiento": fecha_vencimiento
        })

    save_data(data)

    mensaje = f"""Cuenta asignada a cliente {numero_cliente}:

-- *{plataforma.upper()}* --
Correo: {correo}
*Estado:* Vendido
*Fecha de vencimiento:* {fecha_vencimiento}
"""
    boton = crear_boton_whatsapp(numero_cliente, mensaje)
    await update.message.reply_text(mensaje, parse_mode='Markdown', reply_markup=boton)


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args

    if len(args) < 1:
        await update.message.reply_text("Uso correcto:\n/info (número_cliente)")
        return

    numero_cliente = args[0].strip()

    if numero_cliente not in data["clientes"]:
        await update.message.reply_text("No se encontró información para ese número de cliente.")
        return

    mensajes = []
    for compra in data["clientes"][numero_cliente]:
        texto = f"""-- {numero_cliente} --
- {compra['plataforma']}
- {compra['correo']} / {compra['contraseña']}
  - - -   {compra['fecha_vencimiento']}   - - -
"""
        mensajes.append(texto)

    texto_completo = "\n".join(mensajes)
    boton = crear_boton_whatsapp(numero_cliente, texto_completo)
    await update.message.reply_text(texto_completo, reply_markup=boton)


async def renovar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args

    if len(args) < 4:
        await update.message.reply_text("Uso correcto:\n/renovar (número_cliente) (plataforma) (correo) (fecha_vencimiento)")
        return

    numero_cliente = args[0].strip()
    plataforma = args[1].strip()
    correo = args[2].strip()
    fecha_vencimiento = args[3].strip()

    cuenta_actualizada = None
    for c in data["cuentas"]:
        if c["plataforma"].lower() == plataforma.lower() and c["correo"].lower() == correo.lower() and c["cliente"] == numero_cliente:
            c["fecha_vencimiento"] = fecha_vencimiento
            cuenta_actualizada = c
            break

    if not cuenta_actualizada:
        await update.message.reply_text("No se encontró la cuenta para renovar.")
        return

    if numero_cliente in data["clientes"]:
        for compra in data["clientes"][numero_cliente]:
            if compra["plataforma"].lower() == plataforma.lower() and compra["correo"].lower() == correo.lower():
                compra["fecha_vencimiento"] = fecha_vencimiento
                break

    save_data(data)

    mensaje = f"""- - - SERVICIO RENOVADO DE *{plataforma.upper()}* - - -
- Correo: {correo}
- *TOCA RENOVAR:* {fecha_vencimiento}
/// *GRACIAS POR SU PREFERENCIA* ///
"""

    boton = crear_boton_whatsapp(numero_cliente, mensaje)
    await update.message.reply_text(mensaje, parse_mode='Markdown', reply_markup=boton)


async def reemplazar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args

    if len(args) < 4:
        await update.message.reply_text("Uso correcto:\n/reemplazar (plataforma) (correo_viejo) (correo_nuevo) (contraseña_nueva)")
        return

    plataforma = args[0].strip()
    correo_viejo = args[1].strip()
    correo_nuevo = args[2].strip()
    contraseña_nueva = args[3].strip()

    cliente_asignado = None
    cuenta_encontrada = None
    for c in data["cuentas"]:
        if c["plataforma"].lower() == plataforma.lower() and c["correo"].lower() == correo_viejo.lower():
            cliente_asignado = c["cliente"]
            c["correo"] = correo_nuevo
            c["contraseña"] = contraseña_nueva
            cuenta_encontrada = c
            break

    if not cuenta_encontrada:
        await update.message.reply_text("No se encontró la cuenta para reemplazar.")
        return

    if cliente_asignado and cliente_asignado in data["clientes"]:
        for compra in data["clientes"][cliente_asignado]:
            if compra["plataforma"].lower() == plataforma.lower() and compra["correo"].lower() == correo_viejo.lower():
                compra["correo"] = correo_nuevo
                compra["contraseña"] = contraseña_nueva
                break

    save_data(data)

    mensaje = f"""ACTUALIZACIÓN - *{plataforma.upper()}*
- Correo: {correo_nuevo}
- Contraseña: {contraseña_nueva}
"""
    boton = crear_boton_whatsapp(cliente_asignado if cliente_asignado else '', mensaje)
    await update.message.reply_text(mensaje, parse_mode='Markdown', reply_markup=boton)


async def vencidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    hoy = datetime.date.today()
    telefonos_enviados = set()
    mensajes_enviados = 0
    cuentas_modificadas = False

    cuentas_por_cliente = {}

    for c in data["cuentas"]:
        if c["estado"] == "vendido" and c.get("fecha_vencimiento"):
            try:
                try:
                    fecha_venc = datetime.datetime.strptime(c["fecha_vencimiento"], "%Y-%m-%d").date()
                except ValueError:
                    fecha_venc = datetime.datetime.strptime(c["fecha_vencimiento"], "%d/%m/%y").date()
            except Exception as e:
                logging.error(f"Error parsing fecha_vencimiento '{c['fecha_vencimiento']}': {e}")
                continue

            if fecha_venc <= hoy:
                numero_cliente = c.get("cliente")
                if not numero_cliente:
                    logging.warning(f"Cuenta vencida sin cliente asignado: {c}")
                    continue

                if numero_cliente not in cuentas_por_cliente:
                    cuentas_por_cliente[numero_cliente] = []
                cuentas_por_cliente[numero_cliente].append(c)

                c["estado"] = "disponible"
                c["cliente"] = None
                c["fecha_vencimiento"] = ""

                if numero_cliente in data["clientes"]:
                    data["clientes"][numero_cliente] = [
                        compra for compra in data["clientes"][numero_cliente]
                        if not (compra["correo"].lower() == c["correo"].lower() and compra["plataforma"].lower() == c["plataforma"].lower())
                    ]
                    if len(data["clientes"][numero_cliente]) == 0:
                        del data["clientes"][numero_cliente]

                cuentas_modificadas = True

    if cuentas_modificadas:
        save_data(data)

    for numero_cliente, cuentas_cliente in cuentas_por_cliente.items():
        if numero_cliente in telefonos_enviados:
            continue

        if len(cuentas_cliente) == 1:
            c = cuentas_cliente[0]
            texto_msg = (
                f"Buen día, tu servicio de {c['plataforma']} *({c['correo']})* "
                f"a vencido confirma renovación para evitar cortes innecesarios.\n"
                "*METODOS DE PAGO*\n"
                "🟣 YAPE -  926 015 496\n"
                "      ROSALI E. FLORES\n\n"
                "*NO COLOCAR NADA EN LA DESCRIPCIÓN DEL PAGO NO LEEMOS ESA INFORMACION.*"
            )
        else:
            texto_msg = "Buen día, tus servicios streaming han vencido\n"
            for c in cuentas_cliente:
                texto_msg += f"- {c['correo']} ({c['plataforma']})\n"
            texto_msg += (
                "confirma renovación para evitar cortes innecesarios.\n"
                "*METODOS DE PAGO*\n"
                "🟣 YAPE -  926 015 496\n"
                "      ROSALI E. FLORES\n\n"
                "*NO COLOCAR NADA EN LA DESCRIPCIÓN DEL PAGO NO LEEMOS ESA INFORMACION.*"
            )

        boton = crear_boton_whatsapp(numero_cliente, texto_msg)
        await update.message.reply_text(texto_msg, parse_mode='Markdown', reply_markup=boton)
        telefonos_enviados.add(numero_cliente)
        mensajes_enviados += 1

    if mensajes_enviados == 0:
        await update.message.reply_text("No hay cuentas vencidas para notificar.")

async def eliminar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args

    if len(args) < 2:
        await update.message.reply_text("Uso correcto:\n/eliminar (plataforma) (correo)")
        return

    plataforma = args[0].strip()
    correo = args[1].strip()

    cuenta_a_eliminar = None
    for c in data["cuentas"]:
        if c["plataforma"].lower() == plataforma.lower() and c["correo"].lower() == correo.lower():
            cuenta_a_eliminar = c
            break

    if not cuenta_a_eliminar:
        await update.message.reply_text("No se encontró la cuenta para eliminar.")
        return

    cliente = cuenta_a_eliminar.get("cliente")
    fecha_venc = cuenta_a_eliminar.get("fecha_vencimiento", "")

    data["cuentas"].remove(cuenta_a_eliminar)

    if cliente and cliente in data["clientes"]:
        data["clientes"][cliente] = [compra for compra in data["clientes"][cliente] if compra["correo"].lower() != correo.lower()]
        if len(data["clientes"][cliente]) == 0:
            del data["clientes"][cliente]

    save_data(data)

    if cliente:
        texto = f"""Asignar cuenta {plataforma}
({cliente}) // ({fecha_venc})
"""
        boton = crear_boton_whatsapp(cliente, texto)
        await update.message.reply_text(texto, reply_markup=boton)
    else:
        await update.message.reply_text("Cuenta eliminada correctamente.")

    if not cuenta_a_eliminar:
        await update.message.reply_text("No se encontró la cuenta para eliminar.")
        return

    cliente = cuenta_a_eliminar.get("cliente")
    fecha_venc = cuenta_a_eliminar.get("fecha_vencimiento", "")

    data["cuentas"].remove(cuenta_a_eliminar)

    if cliente and cliente in data["clientes"]:
        data["clientes"][cliente] = [compra for compra in data["clientes"][cliente] if compra["correo"].lower() != correo.lower()]
        if len(data["clientes"][cliente]) == 0:
            del data["clientes"][cliente]

    save_data(data)

    if cliente:
        texto = f"""Asignar cuenta {plataforma}
({cliente}) // ({fecha_venc})
"""
        boton = crear_boton_whatsapp(cliente, texto)
        await update.message.reply_text(texto, reply_markup=boton)
    else:
        await update.message.reply_text("Cuenta eliminada correctamente.")

async def sincronizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    cuentas = data.get("cuentas", [])
    clientes = data.get("clientes", {})

    sincronizados = 0
    for num_cliente, compras in list(clientes.items()):
        nuevas_compras = []
        for compra in compras:
            plataforma = compra.get("plataforma", "").lower()
            correo = compra.get("correo", "").lower()

            cuenta_encontrada = None
            for cuenta in cuentas:
                if cuenta.get("plataforma", "").lower() == plataforma and cuenta.get("correo", "").lower() == correo:
                    cuenta_encontrada = cuenta
                    break

            if cuenta_encontrada:
                cuenta_encontrada["estado"] = "vendido"
                cuenta_encontrada["cliente"] = num_cliente
                cuenta_encontrada["fecha_vencimiento"] = compra.get("fecha_vencimiento", "")
                sincronizados += 1
                nuevas_compras.append(compra)

        if nuevas_compras:
            data["clientes"][num_cliente] = nuevas_compras
        else:
            del data["clientes"][num_cliente]

    save_data(data)
    await update.message.reply_text(f"Sincronización completada. Se actualizaron {sincronizados} cuentas y se limpiaron compras inexistentes.")

async def estadisticas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    hoy = datetime.date.today()
    dias_para_alerta = 2

    ganancias = data.get("ganancias", {})
    cuentas = data.get("cuentas", [])
    clientes = data.get("clientes", {})

    texto = "📊 *Estadísticas rápidas* 📊\n\n"

    texto += "💰 *Total de ingresos por plataforma:*\n"
    for plataforma in sorted(ganancias.keys()):
        texto += f"- {plataforma.capitalize()}: S/. {ganancias[plataforma]:.2f}\n"
    if not ganancias:
        texto += "- Sin registros aún\n"
    texto += "\n"

    total_vendidas = sum(1 for c in cuentas if c["estado"] == "vendido")
    texto += f"✅ Total cuentas vendidas: {total_vendidas}\n"

    total_disponibles = sum(1 for c in cuentas if c["estado"] == "disponible")
    texto += f"📦 Total cuentas disponibles: {total_disponibles}\n"

    total_clientes = len(clientes)
    texto += f"👥 Total clientes activos: {total_clientes}\n\n"

    texto += f"⏰ *Cuentas próximas a vencer en {dias_para_alerta} días:*\n"
    proximas = []
    for c in cuentas:
        if c["estado"] == "vendido" and c.get("fecha_vencimiento"):
            try:
                try:
                    fecha_venc = datetime.datetime.strptime(c["fecha_vencimiento"], "%Y-%m-%d").date()
                except ValueError:
                    fecha_venc = datetime.datetime.strptime(c["fecha_vencimiento"], "%d/%m/%y").date()
                delta = (fecha_venc - hoy).days
                if 0 <= delta <= dias_para_alerta:
                    proximas.append((c["plataforma"], c["correo"], c["cliente"], c["fecha_vencimiento"]))
            except Exception as e:
                logging.error(f"Error en fecha vencimiento: {e}")

    if proximas:
        for p in proximas:
            texto += f"- {p[0].capitalize()} ({p[1]}) cliente: {p[2]} vence: {p[3]}\n"
    else:
        texto += "No hay cuentas próximas a vencer.\n"

    await update.message.reply_text(texto, parse_mode="Markdown")

async def buscarcc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Uso correcto:\n/buscarcc (correo_o_plataforma)")
        return
    consulta = args[0].strip().lower()

    resultados = []
    for c in data["cuentas"]:
        if consulta in c["correo"].lower() or consulta in c["plataforma"].lower():
            estado = "Vendido" if c["estado"] == "vendido" else "Disponible"
            cliente = c["cliente"] if c["cliente"] else "Libre"
            resultados.append(f"-- {c['plataforma'].capitalize()} --\nCorreo: {c['correo']}\nEstado: {estado}\nCliente: {cliente}\n")

    if resultados:
        await update.message.reply_text("\n".join(resultados))
    else:
        await update.message.reply_text("No se encontraron cuentas con ese correo o plataforma.")

async def cancelarcompra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Uso correcto:\n/cancelarcompra (número_cliente) (plataforma) (correo)")
        return
    numero_cliente = args[0].strip()
    plataforma = args[1].strip()
    correo = args[2].strip()

    cuenta = None
    for c in data["cuentas"]:
        if c["plataforma"].lower() == plataforma.lower() and c["correo"].lower() == correo.lower() and c["cliente"] == numero_cliente:
            cuenta = c
            break
    if not cuenta:
        await update.message.reply_text("No se encontró la compra para cancelar.")
        return

    cuenta["estado"] = "disponible"
    cuenta["cliente"] = None
    cuenta["fecha_vencimiento"] = ""

    if numero_cliente in data["clientes"]:
        data["clientes"][numero_cliente] = [compra for compra in data["clientes"][numero_cliente]
                                           if not (compra["plataforma"].lower() == plataforma.lower() and compra["correo"].lower() == correo.lower())]
        if len(data["clientes"][numero_cliente]) == 0:
            del data["clientes"][numero_cliente]

    save_data(data)

    await update.message.reply_text(f"Compra cancelada y cuenta liberada para plataforma {plataforma}.")

# --- Servidor Flask para keep-alive ---
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify(status="ok")

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

async def main():
    TOKEN = os.environ.get("TOKEN")
    if not TOKEN:
        print("ERROR: La variable de entorno TOKEN no está definida")
        return

    Thread(target=run_flask).start()

    application = ApplicationBuilder().token(TOKEN).build()

    # Añadir todos los handlers
    application.add_handler(CommandHandler("comandos", comandos))
    application.add_handler(CommandHandler("basecc", basecc))
    application.add_handler(CommandHandler("agregarcc", agregarcc))
    application.add_handler(CommandHandler("comprarcc", comprarcc))
    application.add_handler(CommandHandler("asignarcc", asignarcc))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("renovar", renovar))
    application.add_handler(CommandHandler("reemplazar", reemplazar))
    application.add_handler(CommandHandler("vencidos", vencidos))
    application.add_handler(CommandHandler("vencidas", vencidos))  # Alias con s
    application.add_handler(CommandHandler("eliminar", eliminar))
    application.add_handler(CommandHandler("sincronizar", sincronizar))
    application.add_handler(CommandHandler("estadisticas", estadisticas))
    application.add_handler(CommandHandler("buscarcc", buscarcc))
    application.add_handler(CommandHandler("cancelarcompra", cancelarcompra))

    print("Bot corriendo...")
    await application.run_polling()

import os
import logging
from threading import Thread
from telegram.ext import ApplicationBuilder, CommandHandler
from flask import Flask
import asyncio  # Importamos asyncio para ejecutar la función asincrónica

# Configuración de logging
logging.basicConfig(level=logging.INFO)

# Servidor Flask para mantener el bot activo
app = Flask(__name__)

@app.route('/')
def home():
    return "El bot está corriendo"

def run_flask():
    # Usa el puerto proporcionado por Render (usualmente está en la variable de entorno PORT)
    port = int(os.environ.get('PORT', 8080))  # Si no está configurado, usa 8080 como valor predeterminado
    app.run(host='0.0.0.0', port=port)  # Usa host='0.0.0.0' para que Flask acepte conexiones externas


# Funciones del bot (asegúrate de definirlas)
async def comandos(update, context):
    texto = "Comandos disponibles..."
    await update.message.reply_text(texto)

async def basecc(update, context):
    # Lógica para el comando basecc
    pass

async def agregarcc(update, context):
    # Lógica para agregar cuentas
    pass

# Función principal asincrónica
async def main():
    TOKEN = os.environ.get("TOKEN")
    if not TOKEN:
        print("ERROR: La variable de entorno TOKEN no está definida")
        return

    # Iniciar el servidor Flask en un hilo separado
    Thread(target=run_flask).start()

    # Crear la aplicación de Telegram
    application = ApplicationBuilder().token(TOKEN).build()

    # Añadir todos los handlers
    application.add_handler(CommandHandler("comandos", comandos))
    application.add_handler(CommandHandler("basecc", basecc))
    application.add_handler(CommandHandler("agregarcc", agregarcc))
    # Añadir otros handlers según sea necesario...

    print("Bot corriendo...")
    await application.run_polling()  # Ejecutar el bot en modo asincrónico

# Ejecutar la función principal asincrónica
if __name__ == '__main__':
    asyncio.run(main())  # Usamos asyncio.run para ejecutar la función asincrónica 'main'
