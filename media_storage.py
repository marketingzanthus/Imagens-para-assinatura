"""Separate durable object storage for prize images (private S3 compatible bucket)."""
import mimetypes
import os
import boto3
from botocore.exceptions import ClientError
from flask import abort, redirect, send_from_directory

BUCKET = os.getenv('S3_BUCKET', '')
PREFIX = os.getenv('S3_PREFIX', 'sorteador/').strip('/') + '/'

def client():
    return boto3.client('s3', endpoint_url=os.getenv('S3_ENDPOINT_URL') or None,
                       region_name=os.getenv('S3_REGION', 'us-east-1'))

def save(file, name, local_directory):
    if BUCKET:
        client().upload_fileobj(file.stream, BUCKET, PREFIX + name,
                              ExtraArgs={'ContentType': mimetypes.guess_type(name)[0] or 'application/octet-stream'})
    else:
        if os.getenv('RENDER') == 'true':
            raise RuntimeError('Configure um bucket durável antes de enviar imagens.')
        file.save(os.path.join(local_directory, name))

def serve(name, local_directory):
    if '/' in name or '\\' in name or name.startswith('.'):
        abort(404)
    if BUCKET:
        s3 = client()
        try:
            s3.head_object(Bucket=BUCKET, Key=PREFIX + name)
        except ClientError as error:
            if error.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound'):
                abort(404)
            raise
        return redirect(s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': PREFIX + name}, ExpiresIn=300))
    return send_from_directory(local_directory, name)
