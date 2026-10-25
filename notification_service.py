"""
Centralized Notification Service for BMS College ERP
=====================================================
Provides institutional event routing, in-app notification persistence,
idempotency protection, real-time Flask-SocketIO push to private user/student
rooms, native Web Push (Service Worker + VAPID) for closed-window/background delivery,
OS-level audible chime orchestration, user preferences management, and safe
transaction isolation.
"""

import sys
import os
import json
import base64
import logging
import threading
from datetime import datetime, timedelta
from flask import current_app

logger = logging.getLogger('bms_notifications')

# Global references (configured via init_notifications or dynamically resolved)
_app = None
_db = None
_socketio = None

# VAPID Key File Path
VAPID_FILE = os.path.join(os.path.dirname(__file__), 'vapid_keys.json')
_vapid_public_key = None
_vapid_instance = None

def init_notifications(app, db, socketio):
    """Initializes notification service with core Flask, SQLAlchemy, and SocketIO instances."""
    global _app, _db, _socketio
    _app = app
    _db = db
    _socketio = socketio

def _get_resources():
    """Lazily retrieves app, db, and socketio instances."""
    global _app, _db, _socketio
    if _app is not None and _db is not None and _socketio is not None:
        return _app, _db, _socketio
    
    app_mod = sys.modules.get('app')
    if app_mod:
        if _app is None:
            _app = getattr(app_mod, 'app', None)
        if _db is None:
            _db = getattr(app_mod, 'db', None)
        if _socketio is None:
            _socketio = getattr(app_mod, 'socketio', None)
            
    return _app, _db, _socketio

def _get_models():
    """Lazily retrieves model classes from app module to prevent circular imports."""
    app_mod = sys.modules.get('app')
    if not app_mod:
        raise RuntimeError("App module not loaded.")
    return {
        'Notification': getattr(app_mod, 'Notification'),
        'NotificationPreference': getattr(app_mod, 'NotificationPreference'),
        'PushSubscription': getattr(app_mod, 'PushSubscription', None),
        'User': getattr(app_mod, 'User'),
        'Student': getattr(app_mod, 'Student')
    }

def get_or_create_vapid_keys():
    """
    Returns (public_key_b64, vapid_instance).
    Loads persistent keys from vapid_keys.json or generates and persists a new SECP256R1 pair.
    """
    global _vapid_public_key, _vapid_instance
    if _vapid_public_key and _vapid_instance:
        return _vapid_public_key, _vapid_instance

    from py_vapid import Vapid

    # Try loading existing keyfile
    if os.path.exists(VAPID_FILE):
        try:
            with open(VAPID_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            raw_b64 = data.get('private_key_raw')
            pub_b64 = data.get('public_key')
            if raw_b64 and pub_b64:
                v = Vapid.from_raw(raw_b64.encode('utf-8'))
                _vapid_public_key = pub_b64
                _vapid_instance = v
                return _vapid_public_key, _vapid_instance
        except Exception as e:
            logger.warning(f"Could not load {VAPID_FILE}, generating fresh pair: {e}")

    # Generate new RFC 8292 SECP256R1 keypair
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        priv_key = ec.generate_private_key(ec.SECP256R1())
        priv_num = priv_key.private_numbers().private_value
        raw_bytes = priv_num.to_bytes(32, 'big')
        raw_b64 = base64.urlsafe_b64encode(raw_bytes).rstrip(b'=').decode('utf-8')
        v = Vapid.from_raw(raw_b64.encode('utf-8'))

        raw_pub = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        pub_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b'=').decode('utf-8')

        with open(VAPID_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'public_key': pub_b64,
                'private_key_raw': raw_b64,
                'created_at': datetime.utcnow().isoformat()
            }, f, indent=2)

        _vapid_public_key = pub_b64
        _vapid_instance = v
        return _vapid_public_key, _vapid_instance
    except Exception as gen_err:
        logger.error(f"Failed to generate VAPID keys: {gen_err}")
        return None, None

def get_vapid_public_key():
    """Returns the URL-safe base64 VAPID public key for frontend push subscription."""
    pub_k, _ = get_or_create_vapid_keys()
    return pub_k

def _dispatch_web_push_batch(subs_data, payload_dict):
    """
    Background worker that dispatches Web Push payloads to browser push endpoints
    (Google FCM, Mozilla Autopush, Apple APNs) and cleans up unsubscribed endpoints.
    """
    if not subs_data:
        return
    try:
        from pywebpush import webpush, WebPushException
        pub_key, vapid_obj = get_or_create_vapid_keys()
        if not vapid_obj:
            return

        payload_str = json.dumps(payload_dict)
        claims = {'sub': 'mailto:admin@bmsce.ac.in'}
        expired_ids = []

        for sub in subs_data:
            sub_info = {
                'endpoint': sub['endpoint'],
                'keys': {
                    'p256dh': sub['p256dh_key'],
                    'auth': sub['auth_key']
                }
            }
            try:
                webpush(
                    subscription_info=sub_info,
                    data=payload_str,
                    vapid_private_key=vapid_obj,
                    vapid_claims=claims,
                    timeout=5,
                    ttl=86400
                )
            except WebPushException as wpe:
                if wpe.response is not None and wpe.response.status_code in [404, 410]:
                    expired_ids.append(sub['id'])
                else:
                    logger.debug(f"Web Push dispatch response: {wpe}")
            except Exception as ex:
                logger.debug(f"Web Push delivery notice: {ex}")

        # Clean up stale / expired endpoints
        if expired_ids:
            app_inst, db_inst, _ = _get_resources()
            models = _get_models()
            PushSub = models.get('PushSubscription')
            if app_inst and db_inst and PushSub:
                with app_inst.app_context():
                    try:
                        PushSub.query.filter(PushSub.id.in_(expired_ids)).delete(synchronize_session=False)
                        db_inst.session.commit()
                        logger.info(f"Purged {len(expired_ids)} expired Web Push subscriptions.")
                    except Exception as cleanup_err:
                        db_inst.session.rollback()
                        logger.debug(f"Push subscription cleanup error: {cleanup_err}")
    except Exception as batch_err:
        logger.warning(f"Error in web push background runner: {batch_err}")

def create_notification(
    recipient_type='USER',
    recipient_id=None,
    title='Institutional Notification',
    message='',
    category='general',
    action_url=None,
    idempotency_key=None,
    emit_socket=True,
    sound=True,
    send_email=False,
    email_event=None,
    email_context=None
):
    """
    Creates an authoritative in-app notification with deduplication,
    persists it safely, broadcasts via Socket.IO to the recipient's private room,
    and dispatches background Web Push (with OS sound chime) for closed-window delivery.
    
    Parameters:
    - recipient_type: 'USER' or 'STUDENT'
    - recipient_id: int (User.id or Student.id)
    - title: brief header (max 150 chars)
    - message: notification body text (max 500 chars)
    - category: 'academic', 'attendance', 'marks', 'assignments', 'study_materials',
                'payroll', 'vault', 'security', 'tasks', 'admin', 'general'
    - action_url: destination route/link in ERP
    - idempotency_key: unique string preventing duplicate notification creation
    - emit_socket: whether to send real-time Socket.IO event
    - sound: whether notification qualifies for sound chime playback
    - send_email: optional trigger to dispatch email via existing notify()
    - email_event: event key in NOTIFICATION_ROUTING_MAP
    - email_context: context dictionary for email template
    """
    if not recipient_id:
        logger.warning("create_notification skipped: recipient_id is None")
        return None

    app_inst, db_inst, socketio_inst = _get_resources()
    models = _get_models()
    Notification = models['Notification']
    NotificationPreference = models['NotificationPreference']

    # 1. Idempotency Check (prevent duplicate alerts within 24 hours)
    if idempotency_key:
        try:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            existing = Notification.query.filter(
                Notification.recipient_type == recipient_type,
                Notification.idempotency_key == idempotency_key,
                Notification.timestamp >= cutoff
            ).first()
            if existing:
                # Already dispatched, return existing record
                return existing
        except Exception as idemp_err:
            logger.debug(f"Idempotency lookup notice: {idemp_err}")

    # 2. Automated Recipient Name Personalization
    # Ensures every notification begins with a respectful institutional salutation addressing the recipient.
    formatted_message = (message or '').strip()
    if not formatted_message.startswith('Dear '):
        try:
            if recipient_type == 'STUDENT':
                Student = models['Student']
                st = Student.query.get(recipient_id)
                if st and st.name:
                    formatted_message = f"Dear {st.name},\n{formatted_message}"
            elif recipient_type == 'USER':
                User = models['User']
                u = User.query.get(recipient_id)
                if u:
                    role_lower = (u.role or '').lower()
                    name = u.full_name or u.name or u.username or 'Staff'
                    if not any(name.startswith(p) for p in ['Prof.', 'Dr.', 'Mr.', 'Ms.', 'Mrs.']):
                        honorific = "Prof. " if (role_lower in ['teacher', 'faculty'] or 'hod' in role_lower) else ""
                        name = f"{honorific}{name}"
                    formatted_message = f"Dear {name},\n{formatted_message}"
        except Exception as pers_err:
            logger.debug(f"Recipient personalization lookup notice: {pers_err}")

    # 3. Check user sound and browser preferences
    sound_permitted = sound
    browser_permitted = True
    try:
        pref = None
        if recipient_type == 'USER':
            pref = NotificationPreference.query.filter_by(recipient_type='USER', user_id=recipient_id).first()
        else:
            pref = NotificationPreference.query.filter_by(recipient_type='STUDENT', student_id=recipient_id).first()
        
        if pref:
            if not pref.sound_enabled:
                sound_permitted = False
            elif pref.muted_categories and category in [c.strip() for c in pref.muted_categories.split(',')]:
                sound_permitted = False
            if not pref.browser_enabled:
                browser_permitted = False
    except Exception as pref_err:
        logger.debug(f"Preference check notice: {pref_err}")

    # 4. Create Notification DB Record
    new_notif = None
    try:
        user_id_val = recipient_id if recipient_type == 'USER' else None
        student_id_val = recipient_id if recipient_type == 'STUDENT' else None

        new_notif = Notification(
            user_id=user_id_val,
            student_id=student_id_val,
            recipient_type=recipient_type,
            title=(title or 'Notification')[:150],
            message=formatted_message[:500],
            category=category or 'general',
            action_url=action_url,
            idempotency_key=idempotency_key,
            is_read=False
        )
        db_inst.session.add(new_notif)
        db_inst.session.commit()
    except Exception as db_err:
        try:
            db_inst.session.rollback()
        except Exception:
            pass
        logger.error(f"Failed to persist Notification record: {db_err}")
        return None

    # 5. Real-Time Socket.IO Live Emission to Private User/Student Room (In-App Tab)
    if emit_socket and socketio_inst and new_notif:
        try:
            room_name = f"user_{recipient_id}" if recipient_type == 'USER' else f"student_{recipient_id}"
            unread_count = get_unread_count(recipient_type, recipient_id)
            
            payload = {
                'id': new_notif.id,
                'title': new_notif.title,
                'message': new_notif.message,
                'category': new_notif.category,
                'action_url': new_notif.action_url,
                'timestamp': new_notif.timestamp.strftime('%I:%M %p'),
                'sound': sound_permitted,
                'unread_count': unread_count
            }
            socketio_inst.emit('new_notification', payload, room=room_name)
        except Exception as sock_err:
            logger.warning(f"Socket.IO emission notice for {room_name}: {sock_err}")

    # 6. Web Push Dispatch for Closed-Window / Background Delivery
    if browser_permitted and new_notif:
        try:
            PushSubscription = models.get('PushSubscription')
            if PushSubscription:
                if recipient_type == 'USER':
                    subs = PushSubscription.query.filter_by(recipient_type='USER', user_id=recipient_id).all()
                else:
                    subs = PushSubscription.query.filter_by(recipient_type='STUDENT', student_id=recipient_id).all()
                if subs:
                    subs_data = [{
                        'id': s.id,
                        'endpoint': s.endpoint,
                        'p256dh_key': s.p256dh_key,
                        'auth_key': s.auth_key
                    } for s in subs]
                    push_payload = {
                        'id': new_notif.id,
                        'title': new_notif.title,
                        'message': new_notif.message,
                        'category': new_notif.category,
                        'action_url': new_notif.action_url,
                        'sound': sound_permitted,
                        'tag': f"bms-erp-{new_notif.id}"
                    }
                    threading.Thread(
                        target=_dispatch_web_push_batch,
                        args=(subs_data, push_payload),
                        daemon=True
                    ).start()
        except Exception as push_err:
            logger.warning(f"Web Push dispatch trigger error: {push_err}")

    # 7. Optional Email Channel Dispatch
    if send_email and email_event:
        try:
            app_mod = sys.modules.get('app')
            notify_func = getattr(app_mod, 'notify', None)
            User = models['User']
            Student = models['Student']
            target_obj = User.query.get(recipient_id) if recipient_type == 'USER' else Student.query.get(recipient_id)
            if notify_func and target_obj:
                notify_func(email_event, target_obj, context=email_context or {})
        except Exception as email_err:
            logger.warning(f"Email dispatch error for notification: {email_err}")

    return new_notif

def notify_users(user_ids, title, message, category='general', action_url=None, idempotency_prefix=None, sound=True):
    """Dispatches in-app and background push notifications to a list of User IDs."""
    models = _get_models()
    User = models['User']
    notifications = []
    for uid in user_ids:
        u = User.query.get(uid)
        if not u:
            continue
        idemp = f"{idempotency_prefix}_{uid}" if idempotency_prefix else None
        role_lower = (u.role or '').lower()
        name = u.full_name or u.name or u.username or 'Staff'
        if not any(name.startswith(p) for p in ['Prof.', 'Dr.', 'Mr.', 'Ms.', 'Mrs.']):
            honorific = "Prof. " if (role_lower in ['teacher', 'faculty'] or 'hod' in role_lower) else ""
            name = f"{honorific}{name}"
        user_msg = f"Dear {name},\n{message}" if not message.strip().startswith('Dear ') else message

        n = create_notification(
            recipient_type='USER',
            recipient_id=uid,
            title=title,
            message=user_msg,
            category=category,
            action_url=action_url,
            idempotency_key=idemp,
            sound=sound
        )
        if n:
            notifications.append(n)
    return notifications

def notify_class_students(course, semester, section, title, message, category='general', action_url=None, idempotency_prefix=None, sound=True):
    """Dispatches in-app and background push notifications personalized to all active students in a class."""
    models = _get_models()
    Student = models['Student']
    
    query = Student.query.filter_by(course=course, semester=semester, is_active=True)
    if section and section != 'ALL':
        query = query.filter_by(section=section)
    
    students = query.all()
    notifications = []
    for s in students:
        idemp = f"{idempotency_prefix}_{s.id}" if idempotency_prefix else None
        student_msg = f"Dear {s.name},\n{message}" if not message.strip().startswith('Dear ') else message

        n = create_notification(
            recipient_type='STUDENT',
            recipient_id=s.id,
            title=title,
            message=student_msg,
            category=category,
            action_url=action_url,
            idempotency_key=idemp,
            sound=sound
        )
        if n:
            notifications.append(n)
    return notifications

def notify_role(role_name, title, message, category='general', action_url=None, idempotency_prefix=None, sound=True):
    """Dispatches in-app and background push notifications personalized to all users with a specific role."""
    models = _get_models()
    User = models['User']
    
    if role_name in ['admin', 'HR']:
        users = User.query.filter(User.role.in_(['admin', 'HR'])).all()
    elif 'HOD' in role_name:
        users = User.query.filter(User.role.like('%HOD%')).all()
    else:
        users = User.query.filter_by(role=role_name).all()
        
    notifications = []
    for u in users:
        idemp = f"{idempotency_prefix}_{u.id}" if idempotency_prefix else None
        role_lower = (u.role or '').lower()
        name = u.full_name or u.name or u.username or 'Staff'
        if not any(name.startswith(p) for p in ['Prof.', 'Dr.', 'Mr.', 'Ms.', 'Mrs.']):
            honorific = "Prof. " if (role_lower in ['teacher', 'faculty'] or 'hod' in role_lower) else ""
            name = f"{honorific}{name}"
        user_msg = f"Dear {name},\n{message}" if not message.strip().startswith('Dear ') else message

        n = create_notification(
            recipient_type='USER',
            recipient_id=u.id,
            title=title,
            message=user_msg,
            category=category,
            action_url=action_url,
            idempotency_key=idemp,
            sound=sound
        )
        if n:
            notifications.append(n)
    return notifications

def get_unread_count(recipient_type, recipient_id):
    """Returns the integer unread notifications count for a recipient."""
    models = _get_models()
    Notification = models['Notification']
    
    if recipient_type == 'USER':
        return Notification.query.filter(
            ((Notification.recipient_type == 'USER') & (Notification.user_id == recipient_id)) |
            ((Notification.user_id == recipient_id) & (Notification.recipient_type.is_(None)))
        ).filter_by(is_read=False).count()
    else:
        return Notification.query.filter_by(
            recipient_type='STUDENT',
            student_id=recipient_id,
            is_read=False
        ).count()

def get_notifications_list(recipient_type, recipient_id, limit=20, offset=0, unread_only=False):
    """Retrieves paginated, authorized notification records for recipient."""
    models = _get_models()
    Notification = models['Notification']
    
    if recipient_type == 'USER':
        query = Notification.query.filter(
            ((Notification.recipient_type == 'USER') & (Notification.user_id == recipient_id)) |
            ((Notification.user_id == recipient_id) & (Notification.recipient_type.is_(None)))
        )
    else:
        query = Notification.query.filter_by(
            recipient_type='STUDENT',
            student_id=recipient_id
        )
        
    if unread_only:
        query = query.filter_by(is_read=False)
        
    total_unread = get_unread_count(recipient_type, recipient_id)
    items = query.order_by(Notification.timestamp.desc()).offset(offset).limit(limit).all()
    
    return {
        'unread_count': total_unread,
        'notifications': [
            {
                'id': n.id,
                'title': n.title or 'Notification',
                'message': n.message or '',
                'category': n.category or 'general',
                'action_url': n.action_url,
                'is_read': n.is_read,
                'timestamp': n.timestamp.strftime('%Y-%m-%d %I:%M %p') if n.timestamp else '',
                'time_display': n.timestamp.strftime('%I:%M %p') if n.timestamp else ''
            }
            for n in items
        ]
    }

def mark_as_read(notif_id, recipient_type, recipient_id):
    """Marks a single notification as read if recipient owns it. Returns (success, error_code)."""
    models = _get_models()
    Notification = models['Notification']
    _, db_inst, socketio_inst = _get_resources()
    
    notif = Notification.query.get(notif_id)
    if not notif:
        return False, 404
        
    # Security check: verify ownership
    if recipient_type == 'USER':
        if notif.recipient_type == 'USER' and notif.user_id != recipient_id:
            return False, 403
        if notif.recipient_type == 'STUDENT':
            return False, 403
    elif recipient_type == 'STUDENT':
        if notif.recipient_type != 'STUDENT' or notif.student_id != recipient_id:
            return False, 403
            
    notif.is_read = True
    try:
        db_inst.session.commit()
    except Exception as e:
        db_inst.session.rollback()
        return False, 500
        
    # Update unread badge via Socket.IO
    if socketio_inst:
        try:
            room_name = f"user_{recipient_id}" if recipient_type == 'USER' else f"student_{recipient_id}"
            unread = get_unread_count(recipient_type, recipient_id)
            socketio_inst.emit('unread_count_updated', {'unread_count': unread}, room=room_name)
        except Exception:
            pass
            
    return True, 200

def mark_all_as_read(recipient_type, recipient_id):
    """Marks all unread notifications for recipient as read."""
    models = _get_models()
    Notification = models['Notification']
    _, db_inst, socketio_inst = _get_resources()
    
    try:
        if recipient_type == 'USER':
            Notification.query.filter(
                ((Notification.recipient_type == 'USER') & (Notification.user_id == recipient_id)) |
                ((Notification.user_id == recipient_id) & (Notification.recipient_type.is_(None)))
            ).filter_by(is_read=False).update({'is_read': True}, synchronize_session='fetch')
        else:
            Notification.query.filter_by(
                recipient_type='STUDENT',
                student_id=recipient_id,
                is_read=False
            ).update({'is_read': True}, synchronize_session='fetch')
            
        db_inst.session.commit()
    except Exception as e:
        db_inst.session.rollback()
        return False
        
    if socketio_inst:
        try:
            room_name = f"user_{recipient_id}" if recipient_type == 'USER' else f"student_{recipient_id}"
            socketio_inst.emit('unread_count_updated', {'unread_count': 0}, room=room_name)
        except Exception:
            pass
            
    return True

def get_or_create_preferences(recipient_type, recipient_id):
    """Gets or initializes default notification preferences."""
    models = _get_models()
    NotificationPreference = models['NotificationPreference']
    _, db_inst, _ = _get_resources()
    
    try:
        if recipient_type == 'USER':
            pref = NotificationPreference.query.filter_by(recipient_type='USER', user_id=recipient_id).first()
        else:
            pref = NotificationPreference.query.filter_by(recipient_type='STUDENT', student_id=recipient_id).first()
            
        if not pref:
            pref = NotificationPreference(
                recipient_type=recipient_type,
                user_id=recipient_id if recipient_type == 'USER' else None,
                student_id=recipient_id if recipient_type == 'STUDENT' else None,
                sound_enabled=True,
                browser_enabled=True,
                email_enabled=True,
                volume=0.7,
                muted_categories=''
            )
            db_inst.session.add(pref)
            db_inst.session.commit()
        return pref
    except Exception as e:
        logger.warning(f"Preference lookup fallback: {e}")
        # Return fallback object
        class FallbackPref:
            sound_enabled = True
            browser_enabled = True
            email_enabled = True
            volume = 0.7
            muted_categories = ''
        return FallbackPref()

def update_preferences(recipient_type, recipient_id, sound_enabled=None, browser_enabled=None, email_enabled=None, volume=None, muted_categories=None):
    """Updates preferences for recipient."""
    models = _get_models()
    NotificationPreference = models['NotificationPreference']
    _, db_inst, _ = _get_resources()
    
    pref = get_or_create_preferences(recipient_type, recipient_id)
    if not isinstance(pref, NotificationPreference):
        return False
        
    if sound_enabled is not None:
        pref.sound_enabled = bool(sound_enabled)
    if browser_enabled is not None:
        pref.browser_enabled = bool(browser_enabled)
    if email_enabled is not None:
        pref.email_enabled = bool(email_enabled)
    if volume is not None:
        try:
            pref.volume = max(0.0, min(1.0, float(volume)))
        except (ValueError, TypeError):
            pass
    if muted_categories is not None:
        pref.muted_categories = str(muted_categories)
        
    try:
        db_inst.session.commit()
        return True
    except Exception as e:
        db_inst.session.rollback()
        logger.error(f"Failed to update preferences: {e}")
        return False
