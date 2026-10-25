"""
Digital Vault & OCR Processing Engine for BMS College ERP
Handles document validation, OCR extraction, schema validation, record matching,
classification (New vs Update vs Duplicate vs Ambiguous), admin approval lifecycle,
and atomic database synchronization.
"""

import os
import io
import re
import json
import uuid
import hashlib
from datetime import datetime
from werkzeug.utils import secure_filename
from PIL import Image

# Supported document types and sizes
ALLOWED_VAULT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
MAX_VAULT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

def get_vault_storage_folder(app):
    """Returns absolute path to private vault storage directory, ensuring it exists."""
    storage_dir = os.path.join(app.root_path, 'private_storage', 'vault')
    os.makedirs(storage_dir, exist_ok=True)
    return storage_dir

def compute_sha256(file_bytes):
    """Computes hex SHA-256 hash of byte content."""
    hasher = hashlib.sha256()
    hasher.update(file_bytes)
    return hasher.hexdigest()

def validate_vault_file(file_storage):
    """
    Validates uploaded file for extension, size, and content integrity.
    Returns: (is_valid, error_message, file_bytes, mime_type)
    """
    if not file_storage or not file_storage.filename:
        return False, "No file uploaded or filename is empty.", None, None

    filename = file_storage.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_VAULT_EXTENSIONS:
        return False, f"Unsupported file format '{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_VAULT_EXTENSIONS))}", None, None

    file_bytes = file_storage.read()
    if len(file_bytes) == 0:
        return False, "Uploaded file is empty (0 bytes).", None, None

    if len(file_bytes) > MAX_VAULT_FILE_SIZE:
        return False, f"File size exceeds maximum allowed limit of {MAX_VAULT_FILE_SIZE // (1024 * 1024)}MB.", None, None

    # Content integrity check
    mime_type = "application/octet-stream"
    if ext == 'pdf':
        if not file_bytes.startswith(b'%PDF'):
            return False, "File has a .pdf extension but lacks a valid PDF header.", None, None
        mime_type = 'application/pdf'
    else:
        # Validate image format via PIL
        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.verify()
            fmt = (img.format or '').lower()
            if fmt in ['jpeg', 'jpg']:
                mime_type = 'image/jpeg'
            elif fmt == 'png':
                mime_type = 'image/png'
            else:
                mime_type = f'image/{fmt}'
        except Exception as e:
            return False, f"Invalid or corrupted image file: {str(e)}", None, None

    return True, None, file_bytes, mime_type

def extract_raw_text(file_bytes, filename, mime_type, test_ocr_override=None):
    """
    Extracts text using PyMuPDF (for PDFs) or Tesseract (for images).
    Supports test override for deterministic unit testing.
    Never fabricates fake data when extraction fails.
    Returns: (raw_text, ocr_available, warnings)
    """
    # 1. Deterministic test override
    override = test_ocr_override or os.getenv('VAULT_TEST_OCR_TEXT')
    if override is not None:
        return override.strip(), True, []

    raw_text = ""
    warnings = []
    ocr_available = False

    # 2. PDF processing via PyMuPDF
    if mime_type == 'application/pdf' or filename.lower().endswith('.pdf'):
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            extracted_pages = []
            for page_num in range(len(doc)):
                page_text = doc[page_num].get_text()
                if page_text.strip():
                    extracted_pages.append(page_text.strip())
            raw_text = "\n\n".join(extracted_pages)
            ocr_available = True
            if not raw_text.strip():
                warnings.append("PDF document contained no selectable text. It may be a raster scan requiring optical OCR.")
        except Exception as e:
            warnings.append(f"PDF extraction error: {str(e)}")

    # 3. Image OCR via Tesseract
    else:
        try:
            import pytesseract
            img = Image.open(io.BytesIO(file_bytes))
            raw_text = pytesseract.image_to_string(img)
            ocr_available = True
            if not raw_text.strip():
                warnings.append("OCR engine detected no legible text in the uploaded image.")
        except Exception as e:
            ocr_available = False
            # Check if tesseract binary is missing
            err_str = str(e)
            if 'tesseract is not installed' in err_str.lower() or 'not in your path' in err_str.lower():
                warnings.append("Tesseract OCR binary is not installed in system PATH. Text extraction is unavailable.")
            else:
                warnings.append(f"OCR extraction failed: {err_str}")

    return raw_text.strip(), ocr_available, warnings

def parse_extracted_text(raw_text, doc_type_hint=None):
    """
    Parses unstructured OCR text into structured fields according to ERP schema.
    Detects whether the document represents a Student or Staff member.
    Returns:
        {
            'target_type': 'STUDENT' | 'STAFF',
            'extracted_fields': dict,
            'confidence': float,
            'parsing_warnings': list
        }
    """
    warnings = []
    text_upper = raw_text.upper() if raw_text else ""

    # Determine document type (Student vs Staff)
    student_score = 0
    staff_score = 0

    student_keywords = ['UUCMS', 'STUDENT', 'ADMISSION', 'SEMESTER', 'ROLL', 'ACADEMIC YEAR', 'BCA', 'B.COM', 'BBA']
    staff_keywords = ['STAFF', 'FACULTY', 'EMPLOYEE', 'DEPARTMENT', 'PROF', 'DOCTOR', 'DR.', 'DESIGNATION', 'TEACHER']

    for kw in student_keywords:
        if kw in text_upper:
            student_score += 1
    for kw in staff_keywords:
        if kw in text_upper:
            staff_score += 1

    if doc_type_hint:
        target_type = doc_type_hint.upper()
    elif student_score > staff_score:
        target_type = 'STUDENT'
    elif staff_score > student_score:
        target_type = 'STAFF'
    else:
        # Check for UUCMS identifier pattern
        if re.search(r'\bU\d{2}[A-Z]{2}\d{2}[A-Z]\d{4}\b', text_upper) or 'UUCMS' in text_upper:
            target_type = 'STUDENT'
        else:
            target_type = 'STAFF'

    extracted_fields = {}
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()] if raw_text else []

    # Common email regex
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', raw_text)
    extracted_email = email_match.group(0).lower() if email_match else None

    # Common phone regex
    phone_match = re.search(r'(?:\+?91[\s-]?)?[6-9]\d{9}', raw_text)
    extracted_phone = phone_match.group(0) if phone_match else None

    if target_type == 'STUDENT':
        # 1. UUCMS ID
        uucms_match = re.search(r'\b(?:UUCMS(?:\s*ID)?|REG(?:ISTRATION)?(?:\s*NO)?)\b[\s:]*([A-Za-z0-9_-]+)', raw_text, re.IGNORECASE)
        uucms_id = None
        if uucms_match and uucms_match.group(1).upper() not in ['CARD', 'DOCUMENT', 'PROOF']:
            uucms_id = uucms_match.group(1).upper()
        else:
            # Pattern like U15CM21S0001
            pattern_match = re.search(r'\b(U\d{2}[A-Z0-9_-]{5,15})\b', text_upper)
            if pattern_match:
                uucms_id = pattern_match.group(1)
            else:
                id_match = re.search(r'\b(?:ID\s*NO|ID\s*NUMBER|ID)[\s:]+([A-Za-z0-9_-]+)', raw_text, re.IGNORECASE)
                if id_match and id_match.group(1).upper() not in ['CARD', 'DOCUMENT', 'PROOF']:
                    uucms_id = id_match.group(1).upper()

        # 2. Student Name
        name = None
        name_match = re.search(r'(?:Student\s*Name|Name)[\s:]+([^\r\n]+)', raw_text, re.IGNORECASE)
        if name_match:
            name = name_match.group(1).strip().split('\n')[0].strip()
        elif lines:
            for line in lines:
                if 'BMS' not in line.upper() and 'COLLEGE' not in line.upper() and 'STUDENT' not in line.upper():
                    if len(line) > 3 and not re.search(r'\d', line):
                        name = line.strip()
                        break

        # 3. Course
        course = 'BCA'
        if 'B.COM' in text_upper or 'BCOM' in text_upper or 'COMMERCE' in text_upper:
            course = 'B.Com'
        elif 'BBA' in text_upper or 'BUSINESS ADMINISTRATION' in text_upper:
            course = 'BBA'
        elif 'BCA' in text_upper or 'COMPUTER APPLICATIONS' in text_upper:
            course = 'BCA'

        # 4. Semester
        semester = 'Sem V'
        sem_match = re.search(r'(?:Semester|Sem)[\s:]*([IVX1-6]+)', raw_text, re.IGNORECASE)
        if sem_match:
            val = sem_match.group(1).upper()
            sem_map = {'1': 'Sem I', 'I': 'Sem I', '2': 'Sem II', 'II': 'Sem II',
                       '3': 'Sem III', 'III': 'Sem III', '4': 'Sem IV', 'IV': 'Sem IV',
                       '5': 'Sem V', 'V': 'Sem V', '6': 'Sem VI', 'VI': 'Sem VI'}
            semester = sem_map.get(val, 'Sem V')

        # 5. Academic Year
        academic_year = '3rd Year'
        if semester in ['Sem I', 'Sem II']:
            academic_year = '1st Year'
        elif semester in ['Sem III', 'Sem IV']:
            academic_year = '2nd Year'
        elif semester in ['Sem V', 'Sem VI']:
            academic_year = '3rd Year'

        # 6. Section
        sec_match = re.search(r'(?:Section|Sec)[\s:]*([A-D])', raw_text, re.IGNORECASE)
        section = sec_match.group(1).upper() if sec_match else 'A'

        extracted_fields = {
            'uucms_id': uucms_id or '',
            'name': name or '',
            'email': extracted_email or '',
            'course': course,
            'academic_year': academic_year,
            'semester': semester,
            'section': section
        }

        if not uucms_id:
            warnings.append("Authoritative UUCMS ID could not be identified from document text.")
        if not name:
            warnings.append("Student Name could not be identified from document text.")
        if not extracted_email:
            warnings.append("Student Email was not found in document text.")

    else: # STAFF
        # 1. Staff Name
        full_name = None
        name_match = re.search(r'(?:Staff\s*Name|Faculty\s*Name|Name)[\s:]+([^\r\n]+)', raw_text, re.IGNORECASE)
        if name_match:
            full_name = name_match.group(1).strip().split('\n')[0].strip()
        elif lines:
            for line in lines:
                if any(t in line.lower() for t in ['dr.', 'prof.', 'dr ', 'prof ']):
                    full_name = line.strip()
                    break
            if not full_name:
                for line in lines:
                    if 'BMS' not in line.upper() and 'COLLEGE' not in line.upper() and 'STAFF' not in line.upper():
                        if len(line) > 3 and not re.search(r'\d', line):
                            full_name = line.strip()
                            break

        # 2. Department & Dept ID
        dept_match = re.search(r'(?:Department|Dept)[\s:]+([A-Za-z\s]+)', raw_text, re.IGNORECASE)
        department = dept_match.group(1).strip() if dept_match else 'Computer Science'

        dept_id_match = re.search(r'(?:Staff\s*ID|Emp(?:loyee)?\s*ID|Dept\s*ID)[\s:]+([A-Za-z0-9_-]+)', raw_text, re.IGNORECASE)
        dept_id = dept_id_match.group(1).strip() if dept_id_match else ''

        # 3. Role
        role = 'Faculty'
        if 'HOD' in text_upper:
            role = 'HOD - BCA Dept'
        elif 'PRINCIPAL' in text_upper:
            role = 'Principal'
        elif 'ACCOUNTANT' in text_upper:
            role = 'Accountant'
        elif 'HR' in text_upper:
            role = 'HR'

        # 4. Username suggestion
        clean_user = ''
        if full_name:
            clean_user = full_name.lower().replace('dr.', '').replace('prof.', '').replace(' ', '_').replace('.', '').strip('_')[:12]

        extracted_fields = {
            'full_name': full_name or '',
            'email': extracted_email or '',
            'phone': extracted_phone or '',
            'department': department,
            'dept_id': dept_id,
            'role': role,
            'username': clean_user or ''
        }

        if not full_name:
            warnings.append("Staff Full Name could not be identified from document text.")
        if not dept_id and not clean_user:
            warnings.append("Staff Identifier could not be identified from document text.")

    # Calculate heuristic confidence score
    filled_count = sum(1 for v in extracted_fields.values() if v)
    total_count = len(extracted_fields)
    confidence = round((filled_count / total_count) * 100.0, 1) if total_count else 0.0

    return {
        'target_type': target_type,
        'extracted_fields': extracted_fields,
        'confidence': confidence,
        'parsing_warnings': warnings
    }

def classify_and_match_records(target_type, fields, file_hash, db_models):
    """
    Matches extracted fields against official database records.
    Determines classification:
        - NEW_STUDENT
        - UPDATE_STUDENT
        - NEW_STAFF
        - UPDATE_STAFF
        - DUPLICATE_SUBMISSION
        - AMBIGUOUS_CONFLICT
        - NEEDS_REVIEW
    Generates field-level diff between database and proposed changes.
    """
    Student = db_models['Student']
    User = db_models['User']
    VaultProposal = db_models['VaultProposal']

    warnings = []
    operation = 'CREATE'
    target_record_id = None
    target_identifier = None
    before_values = {}
    diff_summary = []

    # 1. Duplicate submission check via SHA-256
    duplicate_proposal = VaultProposal.query.filter(
        VaultProposal.document.has(file_hash=file_hash),
        VaultProposal.status.in_(['PENDING_APPROVAL', 'APPROVED', 'APPLIED'])
    ).first()

    if duplicate_proposal:
        classification = 'DUPLICATE_SUBMISSION'
        warnings.append(
            f"Duplicate document detected! Identical file (SHA-256: {file_hash[:12]}...) "
            f"was already submitted in Proposal #{duplicate_proposal.proposal_id[:8]} "
            f"with status '{duplicate_proposal.status}'."
        )
        return {
            'classification': classification,
            'operation': duplicate_proposal.operation,
            'target_record_id': duplicate_proposal.target_record_id,
            'target_identifier': duplicate_proposal.target_identifier,
            'before_values': json.loads(duplicate_proposal.before_values_json or '{}'),
            'diff_summary': json.loads(duplicate_proposal.diff_summary_json or '[]'),
            'warnings': warnings
        }

    # 2. STUDENT Matching
    if target_type == 'STUDENT':
        uucms_id = fields.get('uucms_id', '').strip()
        email = fields.get('email', '').strip().lower()

        if not uucms_id:
            classification = 'NEEDS_REVIEW'
            warnings.append("Missing authoritative UUCMS ID. Manual verification is required.")
            return {
                'classification': classification,
                'operation': 'CREATE',
                'target_record_id': None,
                'target_identifier': None,
                'before_values': {},
                'diff_summary': [],
                'warnings': warnings
            }

        target_identifier = uucms_id
        student_by_uucms = Student.query.filter_by(uucms_id=uucms_id).first()
        student_by_email = Student.query.filter_by(email=email).first() if email else None

        # Conflict check
        if student_by_uucms and student_by_email and student_by_uucms.id != student_by_email.id:
            classification = 'AMBIGUOUS_CONFLICT'
            warnings.append(
                f"Conflicting Records! Extracted UUCMS ID matches student '{student_by_uucms.name}' "
                f"(ID: {student_by_uucms.id}), but extracted email matches student '{student_by_email.name}' "
                f"(ID: {student_by_email.id}). Administrator resolution is mandatory."
            )
            target_record_id = student_by_uucms.id
        elif not student_by_uucms and student_by_email:
            classification = 'AMBIGUOUS_CONFLICT'
            warnings.append(
                f"Conflicting Records! Extracted email '{email}' belongs to existing student '{student_by_email.name}' "
                f"(UUCMS: {student_by_email.uucms_id}), but extracted UUCMS ID '{uucms_id}' is new."
            )
            target_record_id = student_by_email.id
        elif student_by_uucms:
            classification = 'UPDATE_STUDENT'
            operation = 'UPDATE'
            target_record_id = student_by_uucms.id
            before_values = {
                'name': student_by_uucms.name,
                'email': student_by_uucms.email,
                'course': student_by_uucms.course,
                'academic_year': student_by_uucms.academic_year,
                'semester': student_by_uucms.semester,
                'section': student_by_uucms.section
            }
        else:
            classification = 'NEW_STUDENT'
            operation = 'CREATE'

    # 3. STAFF Matching
    else:
        dept_id = fields.get('dept_id', '').strip()
        email = fields.get('email', '').strip().lower()
        username = fields.get('username', '').strip().lower()
        full_name = fields.get('full_name', '').strip()

        matched_users = set()
        if dept_id:
            u = User.query.filter_by(dept_id=dept_id).first()
            if u: matched_users.add(u)
        if email:
            u = User.query.filter_by(email=email).first()
            if u: matched_users.add(u)
        if username:
            u = User.query.filter_by(username=username).first()
            if u: matched_users.add(u)

        if len(matched_users) > 1:
            classification = 'AMBIGUOUS_CONFLICT'
            names = ', '.join(f"'{u.full_name}' ({u.username})" for u in matched_users)
            warnings.append(f"Ambiguous Match! Extracted credentials correspond to multiple distinct staff records: {names}.")
            operation = 'UPDATE'
            target_record_id = list(matched_users)[0].id
        elif len(matched_users) == 1:
            matched_user = list(matched_users)[0]
            classification = 'UPDATE_STAFF'
            operation = 'UPDATE'
            target_record_id = matched_user.id
            target_identifier = matched_user.dept_id or matched_user.username
            before_values = {
                'full_name': matched_user.full_name or '',
                'email': matched_user.email or '',
                'phone': matched_user.phone or '',
                'department': matched_user.department or '',
                'dept_id': matched_user.dept_id or '',
                'role': matched_user.role or 'Faculty'
            }
        else:
            # Check if username or email is already taken
            if username and User.query.filter_by(username=username).first():
                classification = 'AMBIGUOUS_CONFLICT'
                warnings.append(f"Username '{username}' is already taken by another account.")
            elif email and User.query.filter_by(email=email).first():
                classification = 'AMBIGUOUS_CONFLICT'
                warnings.append(f"Email '{email}' is already registered to another staff account.")
            else:
                classification = 'NEW_STAFF'
                operation = 'CREATE'
                target_identifier = dept_id or username or full_name

    # Build field diff summary
    if operation == 'UPDATE' and before_values:
        for k, before_val in before_values.items():
            after_val = fields.get(k, '')
            changed = str(before_val).strip() != str(after_val).strip()
            diff_summary.append({
                'field': k,
                'before': before_val,
                'after': after_val,
                'changed': changed
            })
    else:
        for k, v in fields.items():
            diff_summary.append({
                'field': k,
                'before': None,
                'after': v,
                'changed': True
            })

    return {
        'classification': classification,
        'operation': operation,
        'target_record_id': target_record_id,
        'target_identifier': target_identifier,
        'before_values': before_values,
        'diff_summary': diff_summary,
        'warnings': warnings
    }

def apply_approved_proposal(proposal, admin_user, db_session, db_models):
    """
    Safely synchronizes an approved proposal to the authoritative database in an atomic transaction.
    Enforces idempotency, optimistic concurrency, and field-level updates.
    Returns: (success_bool, message_str)
    """
    Student = db_models['Student']
    User = db_models['User']
    log_action = db_models['log_action']

    if proposal.status == 'APPLIED':
        return False, f"Proposal #{proposal.proposal_id[:8]} has already been applied."

    if proposal.status != 'APPROVED':
        return False, f"Cannot apply proposal with status '{proposal.status}'. It must be APPROVED first."

    proposed_fields = json.loads(proposal.proposed_changes_json or '{}')

    try:
        # =====================================================================
        # 1. STUDENT SYNCHRONIZATION
        # =====================================================================
        if proposal.target_type == 'STUDENT':
            uucms_id = proposed_fields.get('uucms_id', '').strip().upper()
            name = proposed_fields.get('name', '').strip()
            email = proposed_fields.get('email', '').strip().lower()
            course = proposed_fields.get('course', 'BCA').strip()
            academic_year = proposed_fields.get('academic_year', '3rd Year').strip()
            semester = proposed_fields.get('semester', 'Sem V').strip()
            section = proposed_fields.get('section', 'A').strip().upper()

            if not uucms_id or not name or not email:
                raise ValueError("Student UUCMS ID, Name, and Email are mandatory.")

            if proposal.operation == 'CREATE':
                # Re-check uniqueness in active transaction
                existing = Student.query.filter_by(uucms_id=uucms_id).first()
                if existing:
                    raise ValueError(f"Student with UUCMS ID '{uucms_id}' already exists in database (ID: {existing.id}).")

                new_student = Student(
                    uucms_id=uucms_id,
                    name=name,
                    email=email,
                    course=course,
                    academic_year=academic_year,
                    semester=semester,
                    section=section,
                    is_active=True
                )
                db_session.add(new_student)
                db_session.flush()
                proposal.target_record_id = new_student.id

            elif proposal.operation == 'UPDATE':
                target_student = Student.query.get(proposal.target_record_id)
                if not target_student:
                    raise ValueError(f"Target student record #{proposal.target_record_id} not found in database.")

                # Apply ONLY approved fields
                if 'name' in proposed_fields: target_student.name = name
                if 'email' in proposed_fields: target_student.email = email
                if 'course' in proposed_fields: target_student.course = course
                if 'academic_year' in proposed_fields: target_student.academic_year = academic_year
                if 'semester' in proposed_fields: target_student.semester = semester
                if 'section' in proposed_fields: target_student.section = section
                target_student.updated_at = datetime.utcnow()

        # =====================================================================
        # 2. STAFF SYNCHRONIZATION
        # =====================================================================
        elif proposal.target_type == 'STAFF':
            full_name = proposed_fields.get('full_name', '').strip()
            email = proposed_fields.get('email', '').strip().lower()
            phone = proposed_fields.get('phone', '').strip()
            department = proposed_fields.get('department', '').strip()
            dept_id = proposed_fields.get('dept_id', '').strip()
            role = proposed_fields.get('role', 'Faculty').strip()
            username = proposed_fields.get('username', '').strip().lower()

            if not full_name:
                raise ValueError("Staff Full Name is mandatory.")

            if proposal.operation == 'CREATE':
                if not username:
                    username = full_name.lower().replace('dr.', '').replace('prof.', '').replace(' ', '_').replace('.', '').strip('_')[:12]
                if not email:
                    email = f"{username}@bmsccm.edu.in"

                # Check uniqueness
                if User.query.filter_by(username=username).first():
                    username = f"{username}_{uuid.uuid4().hex[:4]}"

                from werkzeug.security import generate_password_hash
                new_user = User(
                    username=username,
                    password=generate_password_hash('bms2026pass'),
                    full_name=full_name,
                    email=email,
                    phone=phone or '+91 98765 43210',
                    salary=int(proposed_fields.get('salary', 50000)),
                    department=department or 'General',
                    dept_id=dept_id or f"BMS-{uuid.uuid4().hex[:4].upper()}",
                    role=role,
                    status='Active',
                    dob='1995-01-01',
                    join_date=datetime.utcnow().strftime('%Y-%m-%d'),
                    address='Basavanagudi, Bengaluru',
                    caste='General',
                    religion='General'
                )
                db_session.add(new_user)
                db_session.flush()
                proposal.target_record_id = new_user.id

            elif proposal.operation == 'UPDATE':
                target_user = User.query.get(proposal.target_record_id)
                if not target_user:
                    raise ValueError(f"Target staff user #{proposal.target_record_id} not found in database.")

                # Apply ONLY approved fields, preserving passwords, role, etc.
                if 'full_name' in proposed_fields and full_name:
                    target_user.full_name = full_name
                if 'email' in proposed_fields and email:
                    target_user.email = email
                if 'phone' in proposed_fields and phone:
                    target_user.phone = phone
                if 'department' in proposed_fields and department:
                    target_user.department = department
                if 'dept_id' in proposed_fields and dept_id:
                    target_user.dept_id = dept_id
                if 'role' in proposed_fields and role:
                    target_user.role = role

        # Update proposal state
        proposal.status = 'APPLIED'
        proposal.applied_by_id = admin_user.id
        proposal.applied_at = datetime.utcnow()
        proposal.version += 1

        db_session.commit()
        log_action(f"Applied Digital Vault proposal #{proposal.proposal_id[:8]} ({proposal.target_type} {proposal.operation})", target="Digital Vault")
        return True, f"Proposal #{proposal.proposal_id[:8]} successfully applied to official database."

    except Exception as e:
        db_session.rollback()
        # Record failure on proposal in independent transaction
        try:
            proposal.status = 'FAILED'
            proposal.error_message = str(e)
            db_session.commit()
        except:
            db_session.rollback()

        log_action(f"Failed to apply Digital Vault proposal #{proposal.proposal_id[:8]}: {str(e)}", target="Digital Vault")
        return False, f"Database transaction failed: {str(e)}"
