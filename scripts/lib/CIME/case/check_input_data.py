"""
API for checking input for testcase
"""
from CIME.XML.standard_module_setup import *
from CIME.utils import SharedArea, find_files, safe_copy, expect
from CIME.XML.inputdata import Inputdata
import CIME.Servers

import glob, hashlib, fileinput

logger = logging.getLogger(__name__)
# The inputdata_checksum.dat file will be read into this hash if it's available
chksum_hash = dict()
local_chksum_file = 'inputdata_checksum.dat'

def _download_checksum_file(server, input_data_root, chksum_file):
    """
    Return True if successfully downloaded
    """
    success = False
    rel_path = chksum_file
    full_path = os.path.join(input_data_root, local_chksum_file)
    protocol = type(server).__name__
    logging.info("Trying to download file: '{}' to path '{}' using {} protocol.".format(rel_path, full_path, protocol))
    tmpfile = None
    if os.path.isfile(full_path):
        tmpfile = full_path+".tmp"
        os.rename(full_path, tmpfile)
    # Use umask to make sure files are group read/writable. As long as parent directories
    # have +s, then everything should work.
    with SharedArea():
        success = server.getfile(rel_path, full_path)
        if success:
            if tmpfile:
                _merge_chksum_files(full_path, tmpfile)
                chksum_hash = dict()
        else:
            if tmpfile and os.path.isfile(tmpfile):
                os.rename(tmpfile, full_path)
                logger.warning("Could not automatically download file "+full_path+
                           " Restoring existing version.")
            else:
                logger.warning("Could not automatically download file "+full_path+
                           " download from ftp:ftp.cgd.ucar.edu/cesm/inputdata_checksum.dat")
    return success

def _merge_chksum_files(new_file, old_file):
    with open(old_file) as fin:
        lines = fin.readlines()
    with open(new_file) as fin:
        lines += fin.readlines()
    lines = set(lines)
    with open(new_file, "w") as fout:
        fout.write("".join(lines))
    os.remove(old_file)



def _download_if_in_repo(server, input_data_root, rel_path, isdirectory=False):
    """
    Return True if successfully downloaded
    """
    if not server.fileexists(rel_path):
        return False

    full_path = os.path.join(input_data_root, rel_path)
    logging.info("Trying to download file: '{}' to path '{}' using {} protocol.".format(rel_path, full_path, type(server).__name__))
    # Make sure local path exists, create if it does not
    if isdirectory or full_path.endswith(os.sep):
        if not os.path.exists(full_path):
            logger.info("Creating directory {}".format(full_path))
            os.makedirs(full_path)
        isdirectory = True
    elif not os.path.exists(os.path.dirname(full_path)):
        os.makedirs(os.path.dirname(full_path))

    # Use umask to make sure files are group read/writable. As long as parent directories
    # have +s, then everything should work.
    with SharedArea():
        if isdirectory:
            return server.getdirectory(rel_path, full_path)
        else:
            return server.getfile(rel_path, full_path)

###############################################################################
def check_all_input_data(self, protocol=None, address=None, input_data_root=None, data_list_dir="Buildconf",
                         download=True, chksum=False):
###############################################################################
    success = False
    if protocol is not None and address is not None:
        success = self.check_input_data(protocol=protocol, address=address, download=download,
                                        input_data_root=input_data_root, data_list_dir=data_list_dir, chksum=chksum)
    else:
        success = self.check_input_data(protocol=protocol, address=address, download=False,
                                        input_data_root=input_data_root, data_list_dir=data_list_dir, chksum=chksum)
        if download and not success:
            success = _downloadfromserver(self, input_data_root, data_list_dir)

    expect(not download or (download and success), "Could not find all inputdata on any server")
    self.stage_refcase(input_data_root=input_data_root, data_list_dir=data_list_dir)
    return success

def _downloadfromserver(case, input_data_root, data_list_dir):
    # needs to be downloaded
    success = False
    protocol = 'svn'
    inputdata = Inputdata()
    while not success and protocol is not None:
        protocol, address, user, passwd, chksum_file = inputdata.get_next_server()
        logger.info("Checking server {} with protocol {}".format(address, protocol))
        success = case.check_input_data(protocol=protocol, address=address, download=True,
                                        input_data_root=input_data_root,
                                        data_list_dir=data_list_dir,
                                        user=user, passwd=passwd, chksum_file=chksum_file)
    return success

def stage_refcase(self, input_data_root=None, data_list_dir=None):
    get_refcase  = self.get_value("GET_REFCASE")
    run_type     = self.get_value("RUN_TYPE")
    continue_run = self.get_value("CONTINUE_RUN")

    # We do not fully populate the inputdata directory on every
    # machine and do not expect every user to download the 3TB+ of
    # data in our inputdata repository. This code checks for the
    # existence of inputdata in the local inputdata directory and
    # attempts to download data from the server if it's needed and
    # missing.
    if get_refcase and run_type != "startup" and not continue_run:
        din_loc_root = self.get_value("DIN_LOC_ROOT")
        run_refdate  = self.get_value("RUN_REFDATE")
        run_refcase  = self.get_value("RUN_REFCASE")
        run_refdir   = self.get_value("RUN_REFDIR")
        rundir       = self.get_value("RUNDIR")

        if os.path.isabs(run_refdir):
            refdir = run_refdir
        else:
            refdir = os.path.join(din_loc_root, run_refdir, run_refcase, run_refdate)
            if not os.path.isdir(refdir):
                logger.warning("Refcase not found in {}, will attempt to download from inputdata".format(refdir))
                with open(os.path.join("Buildconf","refcase.input_data_list"),"w") as fd:
                    fd.write("refdir = {}{}".format(refdir, os.sep))
                if input_data_root is None:
                    input_data_root = din_loc_root
                if data_list_dir is None:
                    data_list_dir = "Buildconf"
                success = _downloadfromserver(self, input_data_root=input_data_root, data_list_dir=data_list_dir)
                expect(success, "Could not download refcase from any server")

        logger.info(" - Prestaging REFCASE ({}) to {}".format(refdir, rundir))

        # prestage the reference case's files.

        if (not os.path.exists(rundir)):
            logger.debug("Creating run directory: {}".format(rundir))
            os.makedirs(rundir)

        # copy the refcases' rpointer files to the run directory
        for rpointerfile in glob.iglob(os.path.join("{}","*rpointer*").format(refdir)):
            logger.info("Copy rpointer {}".format(rpointerfile))
            safe_copy(rpointerfile, rundir)

        # link everything else

        for rcfile in glob.iglob(os.path.join(refdir,"*")):
            rcbaseline = os.path.basename(rcfile)
            if not os.path.exists("{}/{}".format(rundir, rcbaseline)):
                logger.info("Staging file {}".format(rcfile))
                os.symlink(rcfile, "{}/{}".format(rundir, rcbaseline))
        # Backward compatibility, some old refcases have cam2 in the name
        # link to local cam file.
        for cam2file in  glob.iglob(os.path.join("{}","*.cam2.*").format(rundir)):
            camfile = cam2file.replace("cam2", "cam")
            os.symlink(cam2file, camfile)
    elif not get_refcase and run_type != "startup":
        logger.info("GET_REFCASE is false, the user is expected to stage the refcase to the run directory.")
        if os.path.exists(os.path.join("Buildconf","refcase.input_data_list")):
            os.remove(os.path.join("Buildconf","refcase.input_data_list"))
    return True

def check_input_data(case, protocol="svn", address=None, input_data_root=None, data_list_dir="Buildconf",
                     download=False, chksum=False, user=None, passwd=None, chksum_file=None):
    """
    Return True if no files missing
    """
    case.load_env(reset=True)
    # Fill in defaults as needed
    input_data_root = case.get_value("DIN_LOC_ROOT") if input_data_root is None else input_data_root

    expect(os.path.isdir(input_data_root), "Invalid input_data_root directory: '{}'".format(input_data_root))
    expect(os.path.isdir(data_list_dir), "Invalid data_list_dir directory: '{}'".format(data_list_dir))

    data_list_files = find_files(data_list_dir, "*.input_data_list")
    expect(data_list_files, "No .input_data_list files found in dir '{}'".format(data_list_dir))

    no_files_missing = True

    if download:
        chksum_hash = dict()
        if protocol not in vars(CIME.Servers):
            logger.warning("Client protocol {} not enabled".format(protocol))
            return False

        if protocol == "svn":
            server = CIME.Servers.SVN(address, user, passwd)
        elif protocol == "gftp":
            server = CIME.Servers.GridFTP(address, user, passwd)
        elif protocol == "ftp":
            server = CIME.Servers.FTP(address, user, passwd)
        elif protocol == "wget":
            server = CIME.Servers.WGET(address, user, passwd)
        else:
            expect(False, "Unsupported inputdata protocol: {}".format(protocol))

    firstdownload = True

    for data_list_file in data_list_files:
        logging.info("Loading input file list: '{}'".format(data_list_file))
        with open(data_list_file, "r") as fd:
            lines = fd.readlines()

        for line in lines:
            line = line.strip()
            if (line and not line.startswith("#")):
                tokens = line.split('=')
                description, full_path = tokens[0].strip(), tokens[1].strip()
                if description.endswith('datapath'):
                    continue
                if(full_path):
                    # expand xml variables
                    full_path = case.get_resolved_value(full_path)
                    rel_path  = full_path.replace(input_data_root, "")
                    model = os.path.basename(data_list_file).split('.')[0]

                    if ("/" in rel_path and rel_path == full_path):
                        # User pointing to a file outside of input_data_root, we cannot determine
                        # rel_path, and so cannot download the file. If it already exists, we can
                        # proceed
                        if not os.path.exists(full_path):
                            logging.warning("Model {} missing file {} = '{}'".format(model, description, full_path))
                            if download:
                                logging.warning("    Cannot download file since it lives outside of the input_data_root '{}'".format(input_data_root))
                            no_files_missing = False
                        else:
                            logging.debug("  Found input file: '{}'".format(full_path))

                    else:
                        # There are some special values of rel_path that
                        # we need to ignore - some of the component models
                        # set things like 'NULL' or 'same_as_TS' -
                        # basically if rel_path does not contain '/' (a
                        # directory tree) you can assume it's a special
                        # value and ignore it (perhaps with a warning)
                        if ("/" in rel_path and not os.path.exists(full_path)):
                            logging.warning("  Model {} missing file {} = '{}'".format(model, description, full_path))
                            no_files_missing = False

                            if (download):
                                if chksum_file and firstdownload:
                                    # Get the md5 checksum file
                                    got_chksum = _download_checksum_file(server, input_data_root, chksum_file)
                                    firstdownload = False
                                isdirectory=rel_path.endswith(os.sep)
                                no_files_missing = _download_if_in_repo(server, input_data_root, rel_path.strip(os.sep),
                                                                        isdirectory=isdirectory)
                                if got_chksum and no_files_missing and not isdirectory:
                                    verify_chksum(input_data_root,chksum_file, rel_path.strip(os.sep))
                        else:
                            if chksum:
                                verify_chksum(input_data_root,chksum_file, rel_path.strip(os.sep))
                                logger.info("Chksum passed for file {}".format(os.path.join(input_data_root,rel_path)))
                            logging.debug("  Already had input file: '{}'".format(full_path))
                else:
                    model = os.path.basename(data_list_file).split('.')[0]
                    logging.warning("Model {} no file specified for {}".format(model, description))

    return no_files_missing


def verify_chksum(input_data_root, checksumfile, filename):
    if not chksum_hash:
        hashfile = os.path.join(input_data_root, local_chksum_file)
        if not os.path.isfile(hashfile):
            expect(False, "Failed to find or download file {}".format(hashfile))

        with open(hashfile) as fd:
            lines = fd.readlines()
            for line in lines:
                lsplit = line.split()
                if len(lsplit) < 8:
                    continue
                # remove the first directory ('inputdata/') from the filename
                fname = (lsplit[7]).split('/',1)[1]
                if fname in chksum_hash.keys():
                    expect(chksum_hash[fname] == lsplit[0], " Inconsistant hashes in chksum for file {}".format(fname))
                else:
                    chksum_hash[fname] = lsplit[0]

    chksum = md5(os.path.join(input_data_root, filename))
    if chksum_hash:
        if not filename in chksum_hash:
            logger.warning("Did not find hash for file {} in chksum file {}".format(filename, checksumfile))
        else:
            expect(chksum == chksum_hash[filename],
                   "chksum mismatch for file {} expected {} found {}".
                   format(os.path.join(input_data_root,filename),chksum, chksum_hash[filename]))



def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
