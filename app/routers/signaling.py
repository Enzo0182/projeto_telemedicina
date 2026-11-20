"""Sinalização WebRTC via WebSocket.

O servidor apenas autentica os participantes e repassa mensagens (offer, answer,
ice, hangup) entre o médico e o paciente da consulta. Nenhum conteúdo de mídia
passa pelo servidor e o conteúdo das mensagens não é registrado em log.
"""
import asyncio
import json
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.auth import SESSION_COOKIE, user_from_token
from app.database import SessionLocal
from app.models import ROLE_DOCTOR, ROLE_PATIENT, Appointment

router = APIRouter()
log = logging.getLogger("telemed.signaling")

RELAY_TYPES = {"offer", "answer", "ice", "hangup"}
MAX_MESSAGE_BYTES = 64 * 1024


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[int, dict[str, WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def join(self, room_id: int, role: str, ws: WebSocket) -> None:
        async with self.lock:
            room = self.rooms.setdefault(room_id, {})
            previous = room.get(role)
            room[role] = ws
            peers = dict(room)
        if previous is not None:
            await _safe_send(previous, {"type": "replaced"})
            try:
                await previous.close(code=4001)
            except RuntimeError:
                pass
        await _safe_send(ws, {"type": "joined", "role": role, "present": sorted(peers)})
        if ROLE_DOCTOR in peers and ROLE_PATIENT in peers:
            # Envia primeiro ao paciente (não iniciador) para que ele esteja pronto antes da oferta do médico.
            await _safe_send(peers[ROLE_PATIENT], {"type": "ready", "initiator": False})
            await _safe_send(peers[ROLE_DOCTOR], {"type": "ready", "initiator": True})

    async def leave(self, room_id: int, role: str, ws: WebSocket) -> None:
        async with self.lock:
            room = self.rooms.get(room_id, {})
            if room.get(role) is not ws:
                return  # já substituído por uma nova conexão
            del room[role]
            others = list(room.values())
            if not room:
                self.rooms.pop(room_id, None)
        for other in others:
            await _safe_send(other, {"type": "peer-left", "role": role})

    async def relay(self, room_id: int, role: str, message: dict) -> None:
        room = self.rooms.get(room_id, {})
        for peer_role, peer in list(room.items()):
            if peer_role != role:
                await _safe_send(peer, message)


manager = RoomManager()


async def _safe_send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:  # conexão já encerrada
        pass


def _authorize(token: str | None, appointment_id: int) -> str | None:
    """Retorna o papel do usuário na consulta, ou None se não autorizado."""
    with SessionLocal() as db:
        user = user_from_token(db, token)
        if user is None:
            return None
        appt = db.get(Appointment, appointment_id)
        if appt is None or not appt.is_confirmed:
            return None
        if user.id == appt.doctor_id and user.is_doctor:
            return ROLE_DOCTOR
        if user.id == appt.patient_id and user.is_patient:
            return ROLE_PATIENT
        return None


def _same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return False
    return urlsplit(origin).netloc == ws.headers.get("host")


@router.websocket("/ws/consultas/{appointment_id}")
async def signaling(ws: WebSocket, appointment_id: int) -> None:
    if not _same_origin(ws):
        await ws.close(code=4403)
        return
    role = await run_in_threadpool(_authorize, ws.cookies.get(SESSION_COOKIE), appointment_id)
    if role is None:
        log.info("Conexão de sinalização recusada (consulta %s)", appointment_id)
        await ws.close(code=4403)
        return
    await ws.accept()
    await manager.join(appointment_id, role, ws)
    log.info("Participante '%s' entrou na sala da consulta %s", role, appointment_id)
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                await _safe_send(ws, {"type": "error", "message": "Mensagem muito grande."})
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get("type") not in RELAY_TYPES:
                continue
            out = {"type": msg["type"], "from": role}
            if msg["type"] in {"offer", "answer"}:
                out["sdp"] = msg.get("sdp")
            elif msg["type"] == "ice":
                out["candidate"] = msg.get("candidate")
            await manager.relay(appointment_id, role, out)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.leave(appointment_id, role, ws)
        log.info("Participante '%s' saiu da sala da consulta %s", role, appointment_id)
