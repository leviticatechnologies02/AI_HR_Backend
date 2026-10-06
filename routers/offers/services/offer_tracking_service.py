from sqlalchemy.orm import Session
from model.models import OfferTracking, OfferStatus, User
from schema.offer_tracking import OfferTrackingCreate, OfferTrackingUpdate
from datetime import datetime
from typing import List, Optional

def create_offer(db: Session, data: OfferTrackingCreate) -> OfferTracking:
    offer = OfferTracking(**data.model_dump())
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer

def get_offers(
    db: Session,
    status: Optional[str] = None,
    candidate_id: Optional[int] = None,
    position: Optional[str] = None,
    user: Optional[User] = None
) -> List[OfferTracking]:
    query = db.query(OfferTracking)

    if user and user.role.lower() != "admin":
        query = query.filter(OfferTracking.created_by == user.id)
    
    if status:
        query = query.filter(OfferTracking.status == status)
    if candidate_id:
        query = query.filter(OfferTracking.candidate_id == candidate_id)
    if position:
        query = query.filter(OfferTracking.position.ilike(f"%{position}%"))
    
    return query.order_by(OfferTracking.created_at.desc()).all()

def get_offer(db: Session, offer_id: int) -> Optional[OfferTracking]:
    return db.query(OfferTracking).filter(OfferTracking.id == offer_id).first()

def update_offer(
    db: Session,
    offer_id: int,
    update_dict: dict
) -> Optional[OfferTracking]:
    """Update an offer"""
    offer = get_offer(db, offer_id)
    if not offer:
        return None
    
    update_dict['updated_at'] = datetime.utcnow()
    
    for key, value in update_dict.items():
        setattr(offer, key, value)
    
    db.commit()
    db.refresh(offer)
    return offer

def update_offer_status(
    db: Session,
    offer_id: int,
    status: OfferStatus
) -> Optional[OfferTracking]:
    offer = get_offer(db, offer_id)
    if not offer:
        return None
    
    offer.status = status
    offer.updated_at = datetime.utcnow()
    
    
    if status == OfferStatus.sent and not offer.sent_date:
        offer.sent_date = datetime.utcnow()
    
    
    if status in [OfferStatus.accepted, OfferStatus.rejected] and not offer.response_date:
        offer.response_date = datetime.utcnow()
    
    db.commit()
    db.refresh(offer)

    # Offer accepted -> start onboarding (invite record + email).
    if status == OfferStatus.accepted:
        from services.offer_onboarding import start_onboarding_for_accepted_offer
        start_onboarding_for_accepted_offer(db, offer)
        db.refresh(offer)
    return offer

def delete_offer(db: Session, offer_id: int) -> bool:
    offer = get_offer(db, offer_id)
    if not offer:
        return False
    
    db.delete(offer)
    db.commit()
    return True

def get_offer_stats(db: Session, user: Optional[User] = None) -> dict:
    query = db.query(OfferTracking)
    
    
    if user and user.role.lower() != "admin":
        query = query.filter(OfferTracking.created_by == user.id)
    
    total = query.count()
    sent = query.filter(OfferTracking.status == OfferStatus.sent).count()
    accepted = query.filter(OfferTracking.status == OfferStatus.accepted).count()
    rejected = query.filter(OfferTracking.status == OfferStatus.rejected).count()
    draft = query.filter(OfferTracking.status == OfferStatus.draft).count()
    
    return {
        "total": total,
        "draft": draft,
        "sent": sent,
        "accepted": accepted,
        "rejected": rejected,
        "acceptance_rate": round((accepted / sent * 100), 2) if sent > 0 else 0
    }

