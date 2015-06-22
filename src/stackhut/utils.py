import subprocess
import logging
from boto.s3.connection import Key, S3Connection
import requests
import barrister
import yaml
import sys
import abc
import uuid
import os
import shutil

# global constants
LOGFILE = 'service.log'
HUTFILE = 'Hutfile'
CONTRACTFILE = 'service.json'
S3_BUCKET = 'stackhut-payloads'
INPUTFILE = 'input.json'
OUTPUTFILE = 'output.json'

# Logging
def setup_logging():
    log = logging.getLogger('stackhut')
    logFormatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s', '%H:%M:%S')
    # file output
    fileHandler = logging.FileHandler(LOGFILE, mode='w')
    fileHandler.setFormatter(logFormatter)
    log.addHandler(fileHandler)
    # console
    consoleHandler = logging.StreamHandler(stream=sys.stdout)
    consoleHandler.setFormatter(logFormatter)
    log.addHandler(consoleHandler)
    return log

log = setup_logging()

def set_log_level(args_level):
    global log
    # setup the logger
    loglevel = logging.WARN
    if args_level == 1:
        loglevel = logging.INFO
    elif args_level >= 2:
        loglevel = logging.DEBUG
    log.setLevel(loglevel)


# Base command implementing common func
class BaseCmd:
    """The Base Command"""
    cmd_name = ''

    def __init__(self):
        self.src_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..'))
        self.shim_dir = os.path.normpath(os.path.join(self.src_dir, '../res/shims'))
        log.debug("StackHut src dir is {}".format(self.src_dir))
        log.debug("StackHut shims dir is {}".format(self.shim_dir))

    @abc.abstractmethod
    def parse_cmds(self, subparsers, description):
        sp = subparsers.add_parser(self.cmd_name, help=description, description=description)
        sp.set_defaults(func=self.run)
        return sp

    @abc.abstractmethod
    def run(self, args):
        """Main entry point for a command with parsed cmd args"""
        # import the hutfile
        self.hutfile = yaml.load(args.hutfile)



# Error handling
class ParseError(barrister.RpcException):
    def __init__(self, data=None):
        code = -32700
        msg = 'Parse Error'
        data = {} if data is not None else data
        super(ParseError, self).__init__(code, msg, data)

class InternalError(barrister.RpcException):
    def __init__(self, data=None):
        code = -32603
        msg = 'Internal Error'
        data = {} if data is not None else data
        super(InternalError, self).__init__(code, msg, data)

class ServerError(barrister.RpcException):
    def __init__(self, code, msg, data=None):
        code = code
        msg = 'Internal Service Error - {}'.format(msg)
        data = {} if data is not None else data
        super(ServerError, self).__init__(code, msg, data)

class NonZeroExitError(barrister.RpcException):
    def __init__(self, exitcode, stderr):
        code = -32001
        msg = 'Service sub-command returned a non-zero exit'
        data = dict(exitcode=exitcode, stderr=stderr)
        super(NonZeroExitError, self).__init__(code, msg, data)


class FileStore:
    """A base wrapper wrapper around S3 task state"""
    @abc.abstractmethod
    def get_string(self, name):
        pass

    @abc.abstractmethod
    def get_file(self, name):
        pass

    @abc.abstractmethod
    def put_string(self, s, name):
        pass

    @abc.abstractmethod
    def put_file(self, fname):
        pass


class S3Store(FileStore):
    def __init__(self, task_id, aws_id, aws_key):
        self.task_id = task_id
        # open connection to AWS
        self.conn = S3Connection(aws_id, aws_key)
        self.bucket = self.conn.get_bucket(S3_BUCKET)

    def _create_key(self, name):
        k = Key(self.bucket)
        k.key = '{}/{}'.format(self.task_id, name)
        return k

    def get_string(self, name):
        k = self._create_key(name)
        s = k.get_contents_as_string(encoding='utf-8')
        log.info("Downloaded {} from S3".format(name))
        return s

    def get_file(self, name):
        pass

    def put_string(self, s, name):
        k = self._create_key(name)
        k.set_contents_from_string(s)
        log.info("Uploaded {} to S3".format(name))

    def put_file(self, fname, make_public=False):
        k = self._create_key(fname)
        k.set_contents_from_filename(fname)
        log.info("Uploaded {} to S3".format(fname))

        res = k
        if make_public:
            k.set_acl('public-read')
            k.make_public()
            res = k.generate_url(expires_in=0, query_auth=False)
        return res

class LocalStore(FileStore):
    local_store = "local_task"

    def __init__(self):
        shutil.rmtree(self.local_store, ignore_errors=True)
        os.mkdir(self.local_store)
        # copy any files that should be there into the dir
        shutil.copy(INPUTFILE, self.local_store)

    def _get_path(self, name):
        return "{}/{}".format(self.local_store, name)

    def get_string(self, name):
        with open(self._get_path(name), "r") as f:
            x = f.read()
        return x

    def get_file(self, name):
        pass

    def put_string(self, s, name):
        with open(self._get_path(name), "w") as f:
            f.write(s)

    def put_file(self, fname, make_public=False):
        shutil.copy(fname, self.local_store)
        return os.path.join(self.local_store, fname)


## S3 helper functions
# File upload / download helpers
def download_file(url, fname=None):
    """from http://stackoverflow.com/questions/16694907/how-to-download-large-file-in-python-with-requests-py"""
    fname = url.split('/')[-1] if fname is None else fname
    logging.info("Downloading file {} from {}".format(fname, url))
    r = requests.get(url, stream=True)
    with open(fname, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:  # filter out keep-alive new chunks
                f.write(chunk)
    return fname


class Subprocess:
    """Subprocess helper functions"""
    @staticmethod
    def call_strings(cmd, stdin):
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr= p.communicate(input=stdin.encode())
            exitcode = p.returncode
        except OSError as e:
            raise ServerError(-32002, 'OS error', dict(error=e.strerror))

        if exitcode is not 0:
            raise NonZeroExitError(exitcode, stderr.decode())
        else:
            return dict(stdout=stdout.decode())

    @staticmethod
    def call_files(cmd, stdin, stdout, stderr):
        ret_val = subprocess.call(cmd, stdin=stdin, stdout=stdout, stderr=stderr)
        return ret_val
