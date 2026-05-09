from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, and_
from typing import Optional
from app.database import get_db, SessionLocal
from app.routers.auth import get_current_user, decode_access_token
from app.models.user import User
from app.models.reel import Conversation, ConversationMember, Message
import json
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/messages", tags=["Messages"])

# WebSocket connection manager
# Keeps track of all active connections
class ConnectionManager:
    def __init__(self):
        # Dict of conversation_id -> list of (websocket, user_id)
        self.active_connections: dict = {}

    async def connect(self, websocket: WebSocket, conversation_id: str, user_id: str):
        await websocket.accept()
        if conversation_id not in self.active_connections:
            self.active_connections[conversation_id] = []
        self.active_connections[conversation_id].append((websocket, user_id))

    def disconnect(self, websocket: WebSocket, conversation_id: str):
        if conversation_id in self.active_connections:
            self.active_connections[conversation_id] = [
                (ws, uid) for ws, uid in self.active_connections[conversation_id]
                if ws != websocket
            ]

    async def broadcast(self, message: dict, conversation_id: str):
        """Send message to all connected users in this conversation."""
        if conversation_id not in self.active_connections:
            return
        dead_connections = []
        for websocket, user_id in self.active_connections[conversation_id]:
            try:
                await websocket.send_json(message)
            except:
                dead_connections.append((websocket, user_id))
        # Clean up dead connections
        for conn in dead_connections:
            self.active_connections[conversation_id].remove(conn)

manager = ConnectionManager()


def get_conversation_detail(db: Session, conversation: Conversation, current_user_id: str):
    """Helper to build conversation response with last message and unread count."""
    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation.id
    ).all()

    last_message = db.query(Message).filter(
        Message.conversation_id == conversation.id
    ).order_by(desc(Message.created_at)).first()

    # Get current user's last read time
    my_membership = next((m for m in members if m.user_id == current_user_id), None)
    last_read = my_membership.last_read_at if my_membership else None

    # Count unread messages
    unread_count = 0
    if last_read:
        unread_count = db.query(Message).filter(
            Message.conversation_id == conversation.id,
            Message.created_at > last_read,
            Message.sender_id != current_user_id
        ).count()

    # For DMs get the other person's info
    other_user = None
    if conversation.type == "dm":
        other_member = next((m for m in members if m.user_id != current_user_id), None)
        if other_member:
            other_user = db.query(User).filter(User.id == other_member.user_id).first()

    return {
        "id": conversation.id,
        "type": conversation.type,
        "name": other_user.full_name if other_user else conversation.name,
        "username": other_user.username if other_user else None,
        "avatar_url": other_user.avatar_url if other_user else conversation.avatar_url,
        "school_name": other_user.school_name if other_user else None,
        "members_count": len(members),
        "last_message": last_message.text if last_message else None,
        "last_message_time": last_message.created_at if last_message else conversation.created_at,
        "unread_count": unread_count,
        "updated_at": conversation.updated_at or conversation.created_at,
    }


class SendMessageRequest(BaseModel):
    text: str

@router.post("/conversations/{conversation_id}/send")
def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check membership
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member")

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Save message
    new_message = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        text=body.text.strip(),
        message_type="text"
    )
    db.add(new_message)

    # Update conversation timestamp
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    if conv:
        conv.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(new_message)

    return {
        "id": new_message.id,
        "text": new_message.text,
        "created_at": new_message.created_at,
    }

@router.get("/conversations")
def get_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all conversations for the current user."""
    memberships = db.query(ConversationMember).filter(
        ConversationMember.user_id == current_user.id
    ).all()

    conversations = []
    for m in memberships:
        conv = db.query(Conversation).filter(Conversation.id == m.conversation_id).first()
        if conv:
            conversations.append(get_conversation_detail(db, conv, current_user.id))

    # Sort by most recent message
    conversations.sort(key=lambda x: x["last_message_time"] or datetime.min, reverse=True)
    return conversations


@router.post("/conversations/dm/{username}")
def start_dm(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start or get existing DM with a user."""
    other_user = db.query(User).filter(User.username == username).first()
    if not other_user:
        raise HTTPException(status_code=404, detail="User not found")

    if other_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot DM yourself")

    # Check if DM already exists between these two users
    my_convs = db.query(ConversationMember).filter(
        ConversationMember.user_id == current_user.id
    ).all()
    my_conv_ids = [m.conversation_id for m in my_convs]

    existing = db.query(ConversationMember).filter(
        ConversationMember.user_id == other_user.id,
        ConversationMember.conversation_id.in_(my_conv_ids)
    ).first()

    if existing:
        conv = db.query(Conversation).filter(
            Conversation.id == existing.conversation_id,
            Conversation.type == "dm"
        ).first()
        if conv:
            return get_conversation_detail(db, conv, current_user.id)

    # Create new DM conversation
    conv = Conversation(type="dm")
    db.add(conv)
    db.flush()

    # Add both users as members
    db.add(ConversationMember(conversation_id=conv.id, user_id=current_user.id))
    db.add(ConversationMember(conversation_id=conv.id, user_id=other_user.id))
    db.commit()

    return get_conversation_detail(db, conv, current_user.id)


@router.post("/conversations/group")
def create_group(
    name: str,
    usernames: str,  # comma separated usernames
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a group conversation."""
    conv = Conversation(type="group", name=name, created_by=current_user.id)
    db.add(conv)
    db.flush()

    # Add creator
    db.add(ConversationMember(conversation_id=conv.id, user_id=current_user.id))

    # Add other members
    for username in usernames.split(","):
        username = username.strip()
        user = db.query(User).filter(User.username == username).first()
        if user and user.id != current_user.id:
            db.add(ConversationMember(conversation_id=conv.id, user_id=user.id))
            # System message
            db.add(Message(
                conversation_id=conv.id,
                message_type="system",
                text=f"{username} joined the group"
            ))

    db.commit()
    return get_conversation_detail(db, conv, current_user.id)


@router.get("/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get messages for a conversation."""
    # Check membership
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member")

    # Mark as read
    member.last_read_at = datetime.utcnow()
    db.commit()

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(desc(Message.created_at)).offset(skip).limit(limit).all()

    result = []
    for m in reversed(messages):  # oldest first
        sender = db.query(User).filter(User.id == m.sender_id).first() if m.sender_id else None
        result.append({
            "id": m.id,
            "text": m.text,
            "message_type": m.message_type,
            "sender_id": m.sender_id,
            "sender_username": sender.username if sender else None,
            "sender_avatar": sender.avatar_url if sender else None,
            "sender_school": sender.school_name if sender else None,
            "created_at": m.created_at,
            "is_mine": m.sender_id == current_user.id,
        })

    return result


@router.websocket("/ws/{conversation_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    conversation_id: str,
    token: str = Query(...)
):
    """
    WebSocket endpoint for real-time messaging.
    Token is passed as query param since WS headers are limited.
    """
    # Authenticate via token
    try:
        user_id = decode_access_token(token)
    except:
        await websocket.close(code=4001)
        return

    db = SessionLocal()
    try:
        # Verify membership
        member = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id
        ).first()

        if not member:
            await websocket.close(code=4003)
            return

        user = db.query(User).filter(User.id == user_id).first()
        await manager.connect(websocket, conversation_id, user_id)

        try:
            while True:
                # Wait for message from client
                data = await websocket.receive_text()
                payload = json.loads(data)

                # Save message to database
                new_message = Message(
                    conversation_id=conversation_id,
                    sender_id=user_id,
                    text=payload.get("text"),
                    message_type="text"
                )
                db.add(new_message)

                # Update conversation timestamp
                conv = db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()
                if conv:
                    conv.updated_at = datetime.utcnow()

                db.commit()
                db.refresh(new_message)

                # Broadcast to all connected users in this conversation
                await manager.broadcast({
                    "id": new_message.id,
                    "text": new_message.text,
                    "message_type": "text",
                    "sender_id": user_id,
                    "sender_username": user.username,
                    "sender_avatar": user.avatar_url,
                    "created_at": new_message.created_at.isoformat(),
                    "is_mine": False,  # recipient sees as not mine
                    "sender_is": user_id,  # frontend uses this to check
                }, conversation_id)

        except WebSocketDisconnect:
            manager.disconnect(websocket, conversation_id)

    finally:
        db.close()