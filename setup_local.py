"""Initialize a local beta; never overwrites existing configuration or records."""
from pathlib import Path
import secrets
root=Path(__file__).parent
if not (root/'.env').exists():
    (root/'.env').write_text('SECRET_KEY='+secrets.token_hex(32)+'\nDATABASE_URL=sqlite:///marketplace.db\nCOOKIE_SECURE=false\nDEMO_BOOKING_ENABLED=true\n')
from app import create_app
from app.models import db
app=create_app()
with app.app_context():db.create_all()
print('Local database initialized. Run: python -m flask --app run create-admin')
