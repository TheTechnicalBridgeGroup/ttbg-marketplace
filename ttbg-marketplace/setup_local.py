"""Initialize a local marketplace; never overwrites existing configuration or records."""
from pathlib import Path
import secrets
root=Path(__file__).parent
if not (root/'.env').exists():
    (root/'.env').write_text('SECRET_KEY='+secrets.token_hex(32)+'\nDATABASE_URL=sqlite:///marketplace.db\nCOOKIE_SECURE=false\n')
from app import create_app
from app.models import db
app=create_app()
from app.upgrade import upgrade
with app.app_context():upgrade()
print('Local database initialized. Run: python -m flask --app run create-admin')
