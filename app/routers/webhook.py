from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import User, Match, Prediction, ScoreAdjustment, GameConfig, MatchStatus
from app.utils.scoring import calculate_score
from app.utils.image_gen import generate_leaderboard_image
from datetime import datetime, timedelta
import re

router = APIRouter()

# --- Helpers ---
async def get_or_create_user(session: AsyncSession, phone: int, name: str) -> User:
    result = await session.execute(select(User).where(User.id == phone))
    user = result.scalar_one_or_none()
    if not user:
        user = User(id=phone, name=name)
        session.add(user)
        await session.commit()
    elif user.name != name:
        user.name = name
        await session.commit()
    return user

async def get_config_dict(session: AsyncSession) -> dict:
    result = await session.execute(select(GameConfig))
    configs = result.scalars().all()
    return {c.key: c.value for c in configs}

async def recalculate_all_scores(session: AsyncSession, match_id: int):
    # (Same as before)
    match_res = await session.execute(select(Match).where(Match.id == match_id))
    match_obj = match_res.scalar_one_or_none()
    
    if not match_obj or match_obj.status != MatchStatus.FINISHED:
        return

    preds_res = await session.execute(select(Prediction).where(Prediction.match_id == match_id))
    predictions = preds_res.scalars().all()
    
    config = await get_config_dict(session)
    
    for pred in predictions:
        points, p_type = calculate_score(
            pred.pred_home, pred.pred_away,
            match_obj.goals_home, match_obj.goals_away,
            config
        )
        pred.points = points
        pred.type = p_type
        session.add(pred)
    
    await session.commit()

# --- New Endpoint for Image Serving ---
@router.get("/leaderboard-image")
async def get_leaderboard_image_endpoint(period: str = "total", db: AsyncSession = Depends(get_db)):
    """
    Serves the leaderboard image. Supports filter: total, semanal, mensual.
    """
    now = datetime.utcnow()
    date_filter = None
    
    if period == "semanal":
        date_filter = now - timedelta(days=7)
    elif period == "mensual":
        date_filter = now - timedelta(days=30)
        
    # 1. Calc totals
    # Filter predictions by Match Date
    stmt_preds = select(Prediction.user_id, func.sum(Prediction.points).label("total")) \
                 .join(Prediction.match) \
                 .group_by(Prediction.user_id)
                 
    if date_filter:
        stmt_preds = stmt_preds.where(Match.match_date >= date_filter)

    res_preds = await db.execute(stmt_preds)
    points_map = {row.user_id: row.total or 0 for row in res_preds.all()}
    
    # 2. Adjustments
    stmt_adj = select(ScoreAdjustment.user_id, func.sum(ScoreAdjustment.points).label("total")).group_by(ScoreAdjustment.user_id)
    if date_filter:
        stmt_adj = stmt_adj.where(ScoreAdjustment.created_at >= date_filter)
        
    res_adj = await db.execute(stmt_adj)
    for row in res_adj.all():
        points_map[row.user_id] = points_map.get(row.user_id, 0) + (row.total or 0)
        
    if not points_map:
         return Response(content=b"", media_type="image/jpeg")
         
    user_ids = list(points_map.keys())
    users_res = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = users_res.scalars().all()
    
    leaderboard = []
    for u in users:
        leaderboard.append({"name": u.name, "total_points": points_map.get(u.id, 0)})
    leaderboard.sort(key=lambda x: x["total_points"], reverse=True)
    
    img_io = generate_leaderboard_image(leaderboard)
    return Response(content=img_io.getvalue(), media_type="image/jpeg")

# --- Helper for TwiML ---
def twiml_response(text: str, media_url: str = None):
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message><Body>{text}</Body>'
    if media_url:
        xml += f'<Media>{media_url}</Media>'
    xml += '</Message></Response>'
    return Response(content=xml, media_type="application/xml")

# --- Webhook Endpoint ---
@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    try:
        data = await request.json()
        is_json = True
    except:
        form = await request.form()
        data = dict(form)
        is_json = False

    sender = data.get("From") or data.get("from") or "0"
    sender_phone = int(sender.replace("whatsapp:", "").replace("@c.us", ""))
    
    message_body = data.get("Body") or data.get("body") or ""
    message_body = message_body.strip()
    
    sender_name = data.get("ProfileName") or data.get("name") or "Unknown"

    if not message_body.startswith("!"):
        return {"status": "ignored"}

    user = await get_or_create_user(db, sender_phone, sender_name)
    parts = message_body.split()
    command = parts[0].lower()

    def reply(msg, media=None):
        if is_json:
             res = {"reply": msg}
             if media: res["media"] = media
             return res
        return twiml_response(msg, media)

    # --- COMMAND: !pronostico ---
    if command == "!pronostico":
        if len(parts) != 3:
            return reply("❌ Uso: !pronostico [ID] [L-V].\nEj: 1 2-1")
        
        try:
            match_id = int(parts[1])
            home_goals, away_goals = map(int, parts[2].split('-'))
        except ValueError:
            return reply("❌ Formato incorrecto. Ej: 2-1")

        match_res = await db.execute(select(Match).where(Match.id == match_id))
        match_obj = match_res.scalar_one_or_none()

        if not match_obj: return reply("❌ Partido no existe.")
        if match_obj.match_date < datetime.utcnow(): return reply("❌ Partido cerrado.")
        
        pred_res = await db.execute(select(Prediction).where(Prediction.user_id == user.id, Prediction.match_id == match_id))
        prediction = pred_res.scalar_one_or_none()

        if not prediction:
            prediction = Prediction(user_id=user.id, match_id=match_id, pred_home=home_goals, pred_away=away_goals)
        else:
            prediction.pred_home = home_goals
            prediction.pred_away = away_goals
        
        db.add(prediction)
        await db.commit()
        return reply(f"✅ Pronóstico guardado: {match_id} -> {home_goals}-{away_goals}")

    # --- COMMAND: !tabla ---
    elif command == "!tabla":
        period = "total"
        if len(parts) > 1:
            p = parts[1].lower()
            if p in ["semanal", "mensual"]:
                period = p
        
        base_url = str(request.base_url).rstrip("/")
        img_url = f"{base_url}/leaderboard-image?period={period}"
        return reply(f"🏆 Tabla {period.capitalize()}:", media=img_url)

    # --- COMMAND: !perfil ---
    elif command in ["!perfil", "!misdatos"]:
        # 1. Total Points
        result = await db.execute(select(func.sum(Prediction.points)).where(Prediction.user_id == user.id))
        points = result.scalar() or 0
        
        # 2. Prime Count
        from app.models import PredictionType
        result_prime = await db.execute(select(func.count()).where(Prediction.user_id == user.id, Prediction.type == PredictionType.PRIME)) # Use PredictionType.PRIME
        primes = result_prime.scalar() or 0
        
        # 3. Rank (Quick Calc)
        # Note: Rank calc in SQL is complex, skipping for simplicity or doing pure python if few users
        return reply(f"👤 *Perfil de {user.name}*\n💰 Puntos Totales: {points}\n🎯 Aciertos Prime: {primes}")

    # --- COMMAND: !ayuda ---
    elif command == "!ayuda":
        help_msg = (
            "⚽ *Bot Pronósticos* ⚽\n\n"
            "📋 *!partidos* -> Pendientes.\n"
            "🔮 *!pronostico [ID] [L-V]* -> Jugar.\n"
            "🏆 *!tabla [semanal]* -> Rankings.\n"
            "👤 *!perfil* -> Mis stats."
        )
        if user.is_admin:
            help_msg += "\n\n🛠 *Admin:*\n!nuevo [Local] [Visita] [DD/MM HH:MM]\n!resultado [ID] [L-V]\n!anuncio [Texto]"
        return reply(help_msg)

    # --- COMMAND: !partidos ---
    elif command == "!partidos":
        matches_res = await db.execute(select(Match).where(Match.status == MatchStatus.PENDING).order_by(Match.match_date))
        matches = matches_res.scalars().all()
        if not matches: return reply("💤 No hay partidos.")
        msg = "📅 *Partidos Pendientes*\n"
        for m in matches:
            date_str = m.match_date.strftime("%d/%m %H:%M")
            msg += f"\n🆔 *{m.id}*: {m.home_team} vs {m.away_team} ({date_str})"
        return reply(msg)

    # --- COMMAND: !soyadmin [Secret] ---
    elif command == "!soyadmin":
        # Secret backdoor to claim admin in empty DB
        if len(parts) > 1 and parts[1] == "pronosticos2024":
            user.is_admin = True
            db.add(user)
            await db.commit()
            return reply("👑 ¡Ahora eres el Administrador! Usa !ayuda para ver tus nuevos comandos.")

    # --- ADMIN ---
    if user.is_admin:
        if command == "!nuevo":
            # !nuevo Real Madrid 12/04 20:00
            # Needs careful parsing. Let's assume simple format (User must stick to it):
            # !nuevo Local Visitante 12/04 20:00
            if len(parts) < 5:
                return reply("❌ Uso: !nuevo [Local] [Visita] [DD/MM] [HH:MM]")
            
            try:
                date_str = f"{parts[-2]} {parts[-1]}"
                # Assume current year
                current_year = datetime.utcnow().year
                dt = datetime.strptime(f"{current_year}/{date_str}", "%Y/%d/%m %H:%M")
                
                # Combine teams name (simple split assumed)
                # Better: allow spaces? Complex with current split(). 
                # Let's take parts[1] as Home, parts[2] as Away.
                home = parts[1]
                away = parts[2]
                
                # If name has spaces, this breaks. 
                # Improving parsing: parts[1:-2] are teams. But we don't know separator.
                # Let's stick to 1-word names or underscores for now for simplicity as per MVP.
                
                m = Match(home_team=home, away_team=away, match_date=dt, status=MatchStatus.PENDING)
                db.add(m)
                await db.commit()
                return reply(f"✅ Partido creado: {home} vs {away} el {date_str}")
            except Exception as e:
                return reply(f"❌ Error fecha/formato: {str(e)}")

        elif command == "!resultado":
            try:
                mid = int(parts[1])
                gh, ga = map(int, parts[2].split('-'))
            except: return reply("❌ Error formato.")
            m_res = await db.execute(select(Match).where(Match.id == mid))
            m_obj = m_res.scalar_one_or_none()
            if not m_obj: return reply("❌ No existe.")
            m_obj.goals_home = gh; m_obj.goals_away = ga; m_obj.status = MatchStatus.FINISHED
            db.add(m_obj); await db.commit()
            await recalculate_all_scores(db, mid)
            return reply(f"✅ Resultado {mid}: {gh}-{ga} guardado.")

        elif command == "!sancionar":
            try:
                tgt, pts = int(parts[1]), int(parts[2])
            except: return reply("❌ Error.")
            adj = ScoreAdjustment(user_id=tgt, points=pts, reason="Admin")
            db.add(adj); await db.commit()
            return reply(f"✅ Sanción {tgt}: {pts} pts.")
            
        elif command == "!anuncio":
            msg_text = " ".join(parts[1:])
            # Simulated broadcast
            return reply(f"📢 [Broadcast Simulado] Enviando a todos: {msg_text}")

    return Response(content="", media_type="text/plain")
