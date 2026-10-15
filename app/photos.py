import io
import warnings
from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from PIL import Image, ImageOps, UnidentifiedImageError
from .models import db, Mentor, MentorPhoto, PhotoSubmission, now
from .security import STAFF_ROLES, account_enabled, log
from .routes import roles
from .control_forms import PhotoForm, PhotoReviewForm

bp=Blueprint('photos',__name__)
MAX_UPLOAD=5*1024*1024

def encode_photo(upload):
    raw=upload.stream.read(MAX_UPLOAD+1)
    if len(raw)>MAX_UPLOAD:raise ValueError('Choose a picture smaller than 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.format not in ('JPEG','PNG','WEBP'):raise ValueError('Upload a JPEG, PNG, or WebP picture.')
                if picture.width*picture.height>16_000_000:raise ValueError('Choose a picture below 16 megapixels.')
                if getattr(picture,'is_animated',False):raise ValueError('Choose a still picture rather than an animation.')
                picture.load()
                picture=ImageOps.exif_transpose(picture)
                picture=ImageOps.fit(picture,(512,512),method=Image.Resampling.LANCZOS)
                if picture.mode in ('RGBA','LA') or 'transparency' in picture.info:
                    rgba=picture.convert('RGBA');background=Image.new('RGB',rgba.size,'white');background.paste(rgba,mask=rgba.getchannel('A'));picture=background
                else:picture=picture.convert('RGB')
                # Re-encode pixels only; no original filename, EXIF, or active content survives.
                out=io.BytesIO();picture.save(out,format='JPEG',quality=85,optimize=True)
                if out.tell()>250_000:raise ValueError('This picture is too complex to store. Try another picture.')
                return out.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise ValueError('The file is not a valid supported picture.') from None

def manage_mentor(mid):
    m=db.get_or_404(Mentor,mid)
    if current_user.role not in STAFF_ROLES and not (current_user.role=='mentor' and m.user_id==current_user.id):abort(403)
    if current_user.role not in STAFF_ROLES and (m.status in ('deleted','suspended') or not account_enabled(m.user)):abort(403)
    return m

def locked_photo(mid):
    # Serialize submissions/decisions for the mentor across web workers.
    m=db.session.execute(db.select(Mentor).where(Mentor.id==mid).with_for_update()).scalar_one()
    photo=db.session.get(MentorPhoto,mid)
    if not photo:photo=MentorPhoto(mentor_id=mid);db.session.add(photo);db.session.flush()
    return m,photo

@bp.route('/mentors/<int:mid>/photo',methods=['GET','POST'])
@login_required
def upload(mid):
    m=manage_mentor(mid);form=PhotoForm()
    if form.validate_on_submit():
        try:content=encode_photo(form.photo.data)
        except ValueError as e:form.photo.errors.append(str(e))
        else:
            m,photo=locked_photo(mid)
            if photo.pending_id:
                old=db.session.get(PhotoSubmission,photo.pending_id)
                old.status='superseded';old.image=None;old.reviewed_at=now()
            item=PhotoSubmission(mentor_id=mid,submitted_by=current_user.id,image=content)
            db.session.add(item);db.session.flush();photo.pending_id=item.id
            log('Profile photo submitted',f'mentor:{mid}',f'Submission {item.id}; pending staff approval.');db.session.commit()
            flash('Picture submitted for review. Your current approved picture stays visible until approval.','success')
            return redirect(url_for('photos.upload',mid=mid))
    history=PhotoSubmission.query.filter_by(mentor_id=mid).order_by(PhotoSubmission.id.desc()).limit(10).all()
    return render_template('photo_upload.html',m=m,form=form,history=history)

@bp.get('/team/photos')
@roles('admin','account_manager','onboarding')
def queue():
    page=PhotoSubmission.query.filter_by(status='pending').order_by(PhotoSubmission.id).paginate(page=request.args.get('page',1,type=int),per_page=12,error_out=False)
    return render_template('photo_queue.html',page=page,form=PhotoReviewForm())

@bp.post('/team/photos/<int:pid>/review')
@roles('admin','account_manager','onboarding')
def review(pid):
    item=db.get_or_404(PhotoSubmission,pid);m=manage_mentor(item.mentor_id);form=PhotoReviewForm()
    if not form.validate_on_submit():abort(400)
    m,photo=locked_photo(m.id)
    db.session.refresh(item)
    if photo.pending_id!=pid or item.status!='pending':
        flash('This submission has already been reviewed or replaced. Refresh the queue.','error');return redirect(url_for('photos.queue'))
    note=(form.note.data or '').strip()
    if form.decision.data=='reject' and not note:
        flash('Add a reason so the mentor knows what to change.','error');return redirect(url_for('photos.queue'))
    if form.decision.data=='approve':
        if photo.approved_id:
            old=db.session.get(PhotoSubmission,photo.approved_id);old.status='superseded';old.image=None
        photo.approved_id=pid;item.status='approved'
    else:item.status='rejected';item.image=None
    item.note=note;item.reviewed_at=now();item.reviewed_by=current_user.id;photo.pending_id=None
    log('Profile photo '+item.status,f'mentor:{m.id}',f'Submission {pid}. '+note);db.session.commit()
    flash('Photo decision saved.','success');return redirect(url_for('photos.queue'))

@bp.post('/team/mentors/<int:mid>/photo/remove')
@roles('admin','account_manager','onboarding')
def remove(mid):
    manage_mentor(mid)
    from .forms import EmptyForm
    if not EmptyForm().validate_on_submit():abort(400)
    m,photo=locked_photo(mid)
    if photo.approved_id:
        item=db.session.get(PhotoSubmission,photo.approved_id);item.status='removed';item.image=None;photo.approved_id=None
        log('Published photo removed',f'mentor:{mid}');db.session.commit()
    flash('Published photo removed.','success');return redirect(url_for('photos.upload',mid=mid))

@bp.get('/team/photos/<int:pid>/image')
@login_required
def private_image(pid):
    item=db.get_or_404(PhotoSubmission,pid)
    if current_user.role not in STAFF_ROLES and item.mentor.user_id!=current_user.id:abort(403)
    if not item.image:abort(404)
    response=send_file(io.BytesIO(item.image),mimetype='image/jpeg',download_name='profile.jpg',max_age=0)
    response.headers['Cache-Control']='private, no-store';return response

@bp.get('/media/mentors/<int:mid>/photo')
def public_image(mid):
    m=db.get_or_404(Mentor,mid)
    if not m.publicly_visible or not m.photo or not m.photo.approved_id:abort(404)
    item=db.session.get(PhotoSubmission,m.photo.approved_id)
    if not item or item.status!='approved' or not item.image:abort(404)
    response=send_file(io.BytesIO(item.image),mimetype='image/jpeg',download_name='profile.jpg',max_age=0)
    response.headers['Cache-Control']='no-store';return response
