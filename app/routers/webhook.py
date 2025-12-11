from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import User, Match, Prediction, ScoreAdjustment, GameConfig, MatchStatus
from app.utils.scoring import calculate_score
from app.utils.image_gen import generate_leaderboard_image
from datetime import datetime
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
    """
    Recalculate scores for a specific match given the real result.
    """
    # Get Match
    match_res = await session.execute(select(Match).where(Match.id == match_id))
    match_obj = match_res.scalar_one_or_none()
    
    if not match_obj or match_obj.status != MatchStatus.FINISHED:
        return

    # Get Predictions
    preds_res = await session.execute(select(Prediction).where(Prediction.match_id == match_id))
    predictions = preds_res.scalars().all()
    
    # Get Config
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

# --- Webhook Endpoint ---

@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Mock webhook receiver for WhatsApp messages.
    Expects JSON payload with 'from', 'body', 'name'.
    """
    # Try JSON first (for local testing), then Form (for Twilio)
    try:
        data = await request.json()
    except:
        form = await request.form()
        data = dict(form)

    # Twilio format: 'From': 'whatsapp:+51999...', 'Body': 'text', 'ProfileName': 'Name'
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

    # --- COMMAND: !pronostico [MatchID] [L-V] ---
    if command == "!pronostico":
        if len(parts) != 3:
            return {"reply": "❌ Uso: !pronostico [ID] [L-V].\nEjemplo: !pronostico 1 2-1\nUsa !partidos para ver los IDs."}
        
        try:
            match_id = int(parts[1])
            score_str = parts[2]
            home_goals, away_goals = map(int, score_str.split('-'))
        except ValueError:
            return {"reply": "❌ Formato incorrecto. Ej: 2-1"}

        # Validate Match
        match_res = await db.execute(select(Match).where(Match.id == match_id))
        match_obj = match_res.scalar_one_or_none()

        if not match_obj:
            return {"reply": "❌ El partido no existe."}
        
        if match_obj.match_date < datetime.utcnow():
            return {"reply": "❌ El partido ya comenzó o terminó. No se aceptan predicciones."}
        
        # Save Prediction (Upsert)
        pred_res = await db.execute(select(Prediction).where(Prediction.user_id == user.id, Prediction.match_id == match_id))
        prediction = pred_res.scalar_one_or_none()

        if not prediction:
            prediction = Prediction(user_id=user.id, match_id=match_id, pred_home=home_goals, pred_away=away_goals)
        else:
            prediction.pred_home = home_goals
            prediction.pred_away = away_goals
        
        db.add(prediction)
        await db.commit()
        return {"reply": f"✅ Pronóstico guardado: Partido {match_id} -> {home_goals}-{away_goals}"}

    # --- COMMAND: !tabla ---
    elif command == "!tabla":
        # Calculate totals
        # Sum points from predictions + score adjustments
        
        # Using a raw query or separate aggregations for simplicity in SQLAlchemy logic
        # 1. Prediction Points
        stmt_preds = select(Prediction.user_id, func.sum(Prediction.points).label("total")).group_by(Prediction.user_id)
        res_preds = await db.execute(stmt_preds)
        points_map = {row.user_id: row.total or 0 for row in res_preds.all()}
        
        # 2. Adjustments
        stmt_adj = select(ScoreAdjustment.user_id, func.sum(ScoreAdjustment.points).label("total")).group_by(ScoreAdjustment.user_id)
        res_adj = await db.execute(stmt_adj)
        for row in res_adj.all():
            points_map[row.user_id] = points_map.get(row.user_id, 0) + (row.total or 0)
            
        # 3. Get User Names
        if not points_map:
             return {"reply": "📉 Aún no hay puntos registrados."}
             
        user_ids = list(points_map.keys())
        users_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        users = users_res.scalars().all()
        
        # Construct Data
        leaderboard = []
        for u in users:
            leaderboard.append({
                "name": u.name,
                "total_points": points_map.get(u.id, 0)
            })
            
        # Sort
        leaderboard.sort(key=lambda x: x["total_points"], reverse=True)
        
        # Generate Image
        img_io = generate_leaderboard_image(leaderboard)
        
        # In a real bot, we would upload this or send bytes. 
        # Here we return a nice message or stream it if hit via browser.
        # Since this is a webhook response returning JSON often used by bots:
        return Response(content=img_io.getvalue(), media_type="image/jpeg")


    # --- COMMAND: !ayuda ---
    elif command == "!ayuda":
        help_msg = (
            "⚽ *Comandos del Bot* ⚽\n\n"
            "📋 *!partidos* -> Ver partidos disponibles y sus IDs.\n"
            "🔮 *!pronostico [ID] [L-V]* -> Enviar tu predicción.\n"
            "   Ej: !pronostico 1 2-1\n"
            "🏆 *!tabla* -> Ver la tabla de posiciones.\n"
        )
        if user.is_admin:
            help_msg += "\n🛠 *Admin:*\n!resultado [ID] [L-V]\n!sancionar [Tel] [Pts]"
            
        return {"reply": help_msg}

    # --- COMMAND: !partidos ---
    elif command == "!partidos":
        matches_res = await db.execute(
            select(Match)
            .where(Match.status == MatchStatus.PENDING)
            .order_by(Match.match_date)
        )
        matches = matches_res.scalars().all()
        
        if not matches:
            return {"reply": "💤 No hay partidos pendientes."}
            
        msg = "📅 *Partidos Pendientes*\n"
        for m in matches:
            date_str = m.match_date.strftime("%d/%m %H:%M")
            msg += f"\n🆔 *{m.id}*: {m.home_team} vs {m.away_team} ({date_str})"
            
        return {"reply": msg}

    # --- ADMIN COMMANDS ---
    if user.is_admin:
        
        # --- COMMAND: !resultado [MatchID] [L-V] ---
        if command == "!resultado":
            if len(parts) != 3:
                return {"reply": "❌ Uso: !resultado [MatchID] [L-V]"}
            
            try:
                match_id = int(parts[1])
                score_str = parts[2]
                gh, ga = map(int, score_str.split('-'))
            except:
                return {"reply": "❌ Error en formato."}
                
            match_res = await db.execute(select(Match).where(Match.id == match_id))
            match_obj = match_res.scalar_one_or_none()
            
            if not match_obj:
                return {"reply": "❌ Partido no encontrado."}
                
            match_obj.goals_home = gh
            match_obj.goals_away = ga
            match_obj.status = MatchStatus.FINISHED
            
            db.add(match_obj)
            await db.commit()
            
            # Recalculate
            await recalculate_all_scores(db, match_id)
            
            return {"reply": f"✅ Resultado actualizado y puntos recalculados para el partido {match_id}."}

        # --- COMMAND: !sancionar @Phone [Points] ---
        elif command == "!sancionar":
            # Assuming format !sancionar 123456789 -5
            if len(parts) != 3:
                return {"reply": "❌ Uso: !sancionar [Telefono] [Puntos]"}
            
            try:
                target_phone = int(parts[1])
                points_delta = int(parts[2])
            except:
                return {"reply": "❌ Error en formato de números."}
                
            adj = ScoreAdjustment(user_id=target_phone, points=points_delta, reason="Sanción Admin")
            db.add(adj)
            await db.commit()
            
            return {"reply": f"✅ Sanción aplicada a {target_phone}: {points_delta} pts."}

    return {"status": "ok", "message": "Command not handled or no permission"}
