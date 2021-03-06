import paramiko
import os
import logging
from tenacity import retry, stop_after_delay, wait_fixed
from crypt4gh.lib import encrypt
from crypt4gh.keys import get_private_key, get_public_key
import boto3


FORMAT = '[%(asctime)s][%(name)s][%(process)d %(processName)s][%(levelname)-8s] (L:%(lineno)s) %(funcName)s: %(message)s'
logging.basicConfig(format=FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
LOG = logging.getLogger(__name__)
# By default the logging level would be INFO
log_level = os.environ.get('DEFAULT_LOG', 'INFO').upper()
LOG.setLevel(log_level)


@retry(wait=wait_fixed(2), stop=(stop_after_delay(14400)))
def open_ssh_connection(hostname, user, key_path, key_pass='password', port=2222):
    """Open an ssh connection, test function."""
    try:
        client = paramiko.SSHClient()
        k = paramiko.RSAKey.from_private_key_file(key_path, password=key_pass)
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname, allow_agent=False, look_for_keys=False,
                       port=port, timeout=15, username=user, pkey=k)
        LOG.info(f'ssh connected to {hostname}:{port} with {user} | PASS |')
    except paramiko.BadHostKeyException as e:
        LOG.error(f'Something went wrong {e}')
        raise Exception('BadHostKeyException on ' + hostname)
    except paramiko.AuthenticationException as e:
        LOG.error(f'Something went wrong {e}')
        raise Exception('AuthenticationException on ' + hostname)
    except paramiko.SSHException as e:
        LOG.error(f'Something went wrong {e}')
        raise Exception('SSHException on ' + hostname)
    finally:
        client.close()


def sftp_upload(hostname, user, file_path, key_path, key_pass='password', port=2222):
    """SFTP Client file upload."""
    try:
        k = paramiko.RSAKey.from_private_key_file(key_path, password=key_pass)
        transport = paramiko.Transport((hostname, port))
        transport.connect(username=user, pkey=k)
        transport.set_keepalive(60)
        LOG.debug(f'sftp connected to {hostname}:{port} with {user}')
        sftp = paramiko.SFTPClient.from_transport(transport)
        filename, _ = os.path.splitext(file_path)
        output_base = os.path.basename(filename)
        if os.path.isfile(file_path):
            sftp.put(file_path, f'{output_base}.c4ga')
        else:
            raise IOError('Could not find localFile {file_path} !!')
        LOG.info(f'file uploaded {output_base}.c4ga | PASS |')
    except Exception as e:
        LOG.error(f'Something went wrong {e}')
        raise e
    finally:
        LOG.debug('sftp done')
        transport.close()


def sftp_remove(hostname, user, file_path, key_path, key_pass='password', port=2222):
    """SFTP Client file upload."""
    try:
        k = paramiko.RSAKey.from_private_key_file(key_path, password=key_pass)
        transport = paramiko.Transport((hostname, port))
        transport.connect(username=user, pkey=k)
        transport.set_keepalive(60)
        LOG.debug(f'sftp connected to {hostname}:{port} with {user}')
        sftp = paramiko.SFTPClient.from_transport(transport)
        filename, _ = os.path.splitext(file_path)
        output_base = os.path.basename(filename)
        sftp.remove(f'{output_base}.c4ga')
        LOG.info(f'Clean up: file removed {output_base}.c4ga')
    except Exception as e:
        LOG.error(f'Something went wrong {e}')
        raise e
    finally:
        LOG.debug('sftp done')
        transport.close()


def s3_connection(address, bucket_name, region_name, access, secret, ssl_enable, root_ca):
    """Upload file to a bucket."""
    boto3.client('s3', endpoint_url=address,
                 use_ssl=ssl_enable, aws_access_key_id=access,
                 aws_secret_access_key=secret,
                 config=boto3.session.Config(signature_version='s3v4'),
                 region_name=region_name,
                 verify=root_ca)
    LOG.debug(f'Connected to S3: {address}.')


def s3_upload(address, bucket_name, region_name, file_path, access, secret, ssl_enable, root_ca):
    """Upload file to a bucket."""
    s3 = boto3.client('s3', endpoint_url=address,
                      use_ssl=ssl_enable, aws_access_key_id=access,
                      aws_secret_access_key=secret,
                      config=boto3.session.Config(signature_version='s3v4'),
                      region_name=region_name,
                      verify=root_ca)
    LOG.debug(f'Connected to S3: {address}.')
    # upload_file method is handled by the S3 Transfer Manager
    # put_object will attempt to send the entire body in one request
    # and does not handle multipart upload
    filename, _ = os.path.splitext(file_path)
    output_base = os.path.basename(filename)
    if os.path.isfile(file_path):
        s3.upload_file(file_path, bucket_name, f'{output_base}.c4ga')
    else:
        raise IOError('Could not find localFile {file_path} !!')
    LOG.info(f'file uploaded {file_path} | PASS |')


def s3_remove(address, bucket_name, region_name, file_path, access, secret, ssl_enable, root_ca):
    """Upload file to a bucket."""
    s3 = boto3.resource('s3', endpoint_url=address,
                        use_ssl=ssl_enable, aws_access_key_id=access,
                        aws_secret_access_key=secret,
                        config=boto3.session.Config(signature_version='s3v4'),
                        region_name=region_name,
                        verify=root_ca)
    LOG.debug(f'Connected to S3: {address}.')
    my_bucket = s3.Bucket(bucket_name)
    filename, _ = os.path.splitext(file_path)
    output_base = os.path.basename(filename)
    my_bucket.delete_key(f'{output_base}.c4ga')


def encrypt_file(file_path, recipient_pubkey, private_key, passphrase):
    """Encrypt file."""
    filename, _ = os.path.splitext(file_path)
    output_file = os.path.expanduser(f'{filename}.c4ga')
    # list of (method, privkey, recipient_pubkey=None)
    # method supported is 0 https://github.com/EGA-archive/crypt4gh/blob/v1.0/crypt4gh/header.py#L261

    def cb():
        return passphrase

    pubkey = get_public_key(recipient_pubkey)
    seckey = get_private_key(private_key, cb)
    keys = [(0, seckey, pubkey)]
    infile = open(file_path, 'rb')
    try:
        encrypt(keys, infile, open(f'{filename}.c4ga', 'wb'), offset=0, span=None)
        print(f'File {filename}.c4ga is the encrypted file.')
    except Exception as e:
        print(f'Something went wrong {e}')
        raise e
    return output_file
