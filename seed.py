import secrets

from app import app, db, User, Student, Office, OfficeStaff, ClearanceRequest, ClearanceItem, notify, log_action

with app.app_context():
    db.drop_all()
    db.create_all()
    from app import seed_defaults
    seed_defaults()

    admin = User.query.filter_by(username="admin").first()
    student_user = User(username="2026-0001", email="juan.delacruz@spus.edu.ph", role="student")
    student_user.set_password(secrets.token_urlsafe(32))
    student = Student(user=student_user, student_id="2026-0001", first_name="Juan", middle_name="Santos", last_name="Dela Cruz", contact_number="09171234567", program="BS Information Technology", year_level="3rd Year", section="A", academic_year="2026-2027")
    db.session.add(student_user)
    db.session.flush()
    staff_accounts = []
    for office in Office.query.filter_by(is_active=True).order_by(Office.id).all():
        username = f"{office.name.lower().replace('/', '-').replace(' ', '-')}.staff"
        staff_user = User(username=username, email=f"{username}@spc-surigao.edu.ph", role="staff")
        staff_user.set_password("Staff123!")
        db.session.add(staff_user)
        db.session.flush()
        db.session.add(OfficeStaff(user_id=staff_user.id, office_id=office.id))
        staff_accounts.append((office.name, username))
    clearance = ClearanceRequest(student=student, academic_year="2026-2027")
    db.session.add(clearance)
    db.session.flush()
    for office in Office.query.filter_by(is_active=True).all():
        item = ClearanceItem(clearance=clearance, office=office, status="approved" if office.name == "Registrar" else "pending")
        db.session.add(item)
    clearance.refresh_status()
    notify(student_user, "Demo clearance ready", "Your seeded development clearance is ready for review.")
    log_action("Seeded demo data", "Development sample records were created.", admin)
    db.session.commit()
    print("Development data created.")
    print("Admin: admin / Admin123!")
    print("Office staff accounts: all use password Staff123!")
    for office_name, username in staff_accounts:
        print(f"{office_name}: {username}")
    print("Student: 2026-0001 / sign in with the matching school Google account")
