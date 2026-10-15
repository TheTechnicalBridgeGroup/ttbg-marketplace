"""Role-protected documentation with safe text rendering and bounded, compressed images."""
import io
import warnings
from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, TextAreaField, SelectField, IntegerField
from wtforms.validators import DataRequired, Length, Optional, NumberRange
from wtforms.widgets import HiddenInput
from PIL import Image, ImageOps, UnidentifiedImageError
from markupsafe import Markup, escape
from sqlalchemy import or_
from .models import db, KnowledgePage, KnowledgeImage, now
from .routes import roles
from .security import log

bp=Blueprint('knowledge',__name__)
READERS=('admin','account_manager','mentor')
EDITORS=('admin','account_manager')

class PageForm(FlaskForm):
    title=StringField('Page title',validators=[DataRequired(),Length(max=160)])
    space=StringField('Space',validators=[DataRequired(),Length(max=80)])
    parent_id=SelectField('Parent page',coerce=int,choices=[])
    body=TextAreaField('Page content',validators=[DataRequired(),Length(max=50000)])
    version=IntegerField(widget=HiddenInput(),validators=[Optional(),NumberRange(min=1)])
    image=FileField('Add an image (optional)')
    caption=StringField('Image description',validators=[Optional(),Length(max=200)])

class VersionForm(FlaskForm):
    version=IntegerField(widget=HiddenInput(),validators=[DataRequired(),NumberRange(min=1)])

def encode_image(upload):
    raw=upload.stream.read(5*1024*1024+1)
    if len(raw)>5*1024*1024:raise ValueError('Choose an image smaller than 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('JPEG','PNG','WEBP') or getattr(source,'is_animated',False):
                    raise ValueError('Choose a still JPEG, PNG, or WebP image.')
                if source.width*source.height>16_000_000:raise ValueError('Choose an image below 16 megapixels.')
                source.load();picture=ImageOps.exif_transpose(source).convert('RGBA')
                picture.thumbnail((1600,1600),Image.Resampling.LANCZOS)
                canvas=Image.new('RGB',picture.size,'white');canvas.paste(picture,mask=picture.getchannel('A'))
                for quality in (80,65,50,35):
                    out=io.BytesIO();canvas.save(out,format='WEBP',quality=quality,method=4)
                    if out.tell()<=500_000:return out.getvalue()
                raise ValueError('This image is too complex. Choose a smaller image.')
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise ValueError('The file is not a supported image.') from None

def body_html(text):
    # Text is always escaped. No raw HTML, remote images, scripts, or unsafe Markdown links.
    parts=[];paragraph=[];listing=False
    def flush():
        if paragraph:parts.append('<p>'+'<br>'.join(paragraph)+'</p>');paragraph.clear()
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('- '):
            flush()
            if not listing:parts.append('<ul>');listing=True
            parts.append('<li>'+str(escape(line[2:]))+'</li>');continue
        if listing:parts.append('</ul>');listing=False
        if not line:flush();continue
        level=next((n for n in (3,2,1) if line.startswith('#'*n+' ')),None)
        if level:
            flush();parts.append(f'<h{level+1}>'+str(escape(line[level+1:]))+f'</h{level+1}>')
        else:paragraph.append(str(escape(line)))
    if listing:parts.append('</ul>')
    flush();return Markup(''.join(parts))

def lock_pages():
    from .models import PlatformSettings
    from .security import settings
    settings()
    db.session.execute(db.select(PlatformSettings).where(PlatformSettings.id==1).with_for_update()).scalar_one()
    db.session.expire_all()

def page_list():return KnowledgePage.query.order_by(KnowledgePage.space,KnowledgePage.title).all()
def navigation(pages):
    by_parent={}
    for page in pages:by_parent.setdefault(page.parent_id,[]).append(page)
    result=[];seen=set()
    def walk(page,depth):
        if page.id in seen:return
        seen.add(page.id);result.append((page,min(depth,6)))
        for child in by_parent.get(page.id,[]):walk(child,depth+1)
    for page in pages:
        if not page.parent_id:walk(page,0)
    for page in pages:walk(page,0)
    return result

def context(**kwargs):return dict(nav_pages=navigation(page_list()),can_edit=current_user.role in EDITORS,**kwargs)

@bp.get('/documentation')
@roles(*READERS)
def index():
    q=request.args.get('q','').strip()[:100];space=request.args.get('space','').strip()[:80]
    query=KnowledgePage.query
    if q:query=query.filter(or_(KnowledgePage.title.icontains(q,autoescape=True),KnowledgePage.body.icontains(q,autoescape=True)))
    if space:query=query.filter_by(space=space)
    pages=query.order_by(KnowledgePage.updated_at.desc()).paginate(page=request.args.get('page',1,type=int),per_page=20,error_out=False)
    return render_template('knowledge/index.html',**context(pages=pages,q=q,space=space))

@bp.get('/documentation/<int:pid>')
@roles(*READERS)
def view(pid):
    page=db.get_or_404(KnowledgePage,pid);form=VersionForm(version=page.version)
    return render_template('knowledge/view.html',**context(page=page,content=body_html(page.body),form=form,
        parent=db.session.get(KnowledgePage,page.parent_id) if page.parent_id else None,
        children=KnowledgePage.query.filter_by(parent_id=pid).order_by(KnowledgePage.title).all(),
        images=KnowledgeImage.query.filter_by(page_id=pid).order_by(KnowledgeImage.id).all()))

@bp.route('/documentation/new',methods=['GET','POST'])
@bp.route('/documentation/<int:pid>/edit',methods=['GET','POST'])
@roles(*EDITORS)
def edit(pid=None):
    if request.method=='POST':lock_pages()
    page=db.get_or_404(KnowledgePage,pid) if pid else None
    form=PageForm(obj=page)
    pages=page_list()
    form.parent_id.choices=[(0,'No parent — top-level page')]+[(p.id,p.space+' / '+p.title) for p in pages if p.id!=pid]
    if request.method=='GET':
        form.parent_id.data=page.parent_id or 0 if page else request.args.get('parent',0,type=int)
        if not page:
            parent=db.session.get(KnowledgePage,form.parent_id.data) if form.parent_id.data else None
            form.space.data=parent.space if parent else 'Getting started'
    if form.validate_on_submit():
        by_id={p.id:p for p in pages};ancestor=form.parent_id.data;seen={pid} if pid else set()
        while ancestor:
            if ancestor in seen:form.parent_id.errors.append('Choose a parent outside this page’s descendants.');break
            seen.add(ancestor);ancestor=by_id[ancestor].parent_id
        if form.parent_id.data and by_id[form.parent_id.data].space!=form.space.data.strip():
            form.space.errors.append('A child page must use its parent’s space.')
        if page and any(p.parent_id==pid and p.space!=form.space.data.strip() for p in pages):
            form.space.errors.append('Move child pages before changing this page’s space.')
        image_data=None
        if form.image.data:
            if not (form.caption.data or '').strip():form.caption.errors.append('Describe the image for readers using assistive technology.')
            try:image_data=encode_image(form.image.data)
            except ValueError as e:form.image.errors.append(str(e))
        if not form.errors:
            if page:
                # Atomic version check serializes page and attachment changes across workers.
                count=KnowledgePage.query.filter_by(id=pid,version=form.version.data).update({'version':KnowledgePage.version+1},synchronize_session=False)
                if count!=1:db.session.rollback();return render_template('knowledge/conflict.html'),409
                db.session.refresh(page)
            else:
                page=KnowledgePage();db.session.add(page)
            if image_data and pid and KnowledgeImage.query.filter_by(page_id=pid).count()>=10:
                db.session.rollback();form.image.errors.append('Each page can have up to 10 images. Remove one first.')
            else:
                page.title=form.title.data.strip();page.space=form.space.data.strip();page.body=form.body.data.strip()
                page.parent_id=form.parent_id.data or None;page.updated_by=current_user.id;page.updated_at=now()
                db.session.flush()
                if image_data:db.session.add(KnowledgeImage(page_id=page.id,caption=form.caption.data.strip(),image=image_data))
                log('Documentation updated' if pid else 'Documentation created',f'document:{page.id}',page.title)
                db.session.commit();flash('Documentation saved.','success');return redirect(url_for('knowledge.view',pid=page.id))
    return render_template('knowledge/edit.html',**context(page=page,form=form))

@bp.route('/documentation/<int:pid>/delete',methods=['GET','POST'])
@roles(*EDITORS)
def delete(pid):
    if request.method=='POST':lock_pages()
    page=db.get_or_404(KnowledgePage,pid);form=VersionForm(version=page.version if request.method=='GET' else None)
    if form.validate_on_submit():
        if KnowledgePage.query.filter_by(id=pid,version=form.version.data).update({'version':KnowledgePage.version+1},synchronize_session=False)!=1:
            db.session.rollback();return render_template('knowledge/conflict.html'),409
        KnowledgePage.query.filter_by(parent_id=pid).update({'parent_id':page.parent_id,'version':KnowledgePage.version+1},synchronize_session=False)
        KnowledgeImage.query.filter_by(page_id=pid).delete(synchronize_session=False)
        log('Documentation deleted',f'document:{pid}',page.title)
        db.session.delete(page);db.session.commit();flash('Page and its images deleted. Child pages were kept.','success')
        return redirect(url_for('knowledge.index'))
    return render_template('knowledge/delete.html',page=page,form=form)

@bp.post('/documentation/images/<int:iid>/delete')
@roles(*EDITORS)
def delete_image(iid):
    lock_pages()
    item=db.get_or_404(KnowledgeImage,iid);form=VersionForm()
    if not form.validate_on_submit():abort(400)
    pid=item.page_id
    if KnowledgePage.query.filter_by(id=pid,version=form.version.data).update({'version':KnowledgePage.version+1,'updated_by':current_user.id,'updated_at':now()},synchronize_session=False)!=1:
        db.session.rollback();return render_template('knowledge/conflict.html'),409
    db.session.delete(item);log('Documentation image removed',f'document:{pid}');db.session.commit()
    return redirect(url_for('knowledge.view',pid=pid))

@bp.get('/documentation/images/<int:iid>')
@roles(*READERS)
def image(iid):
    item=db.get_or_404(KnowledgeImage,iid)
    response=send_file(io.BytesIO(item.image),mimetype='image/webp',download_name='documentation.webp',max_age=0)
    response.headers['Cache-Control']='private, no-store';return response
