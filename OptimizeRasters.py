#------------------------------------------------------------------------------
# Copyright 2015 Esri
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#------------------------------------------------------------------------------
# Name: OptimizeRasters.py
# Description: Optimizes rasters via gdal_translate/gdaladdo
# Version: 20150504
# Requirements: Python
# Required Arguments: -input -output
# Optional Arguments: -cache -config -quality -prec -pyramids -s3input
# -tempinput -tempoutput -subs
# Usage: python.exe OptimizeRasters.py <arguments>
# Notes: OptimizeRasters.xml (config) file is placed alongside OptimizeRasters.py
# OptimizeRasters.py is entirely case-sensitive, extensions/paths in the config
# file are case-sensitive and the program will fail if the correct paths are not
# entered at the cmd-line or in the config file.
# Author: Esri Imagery Workflows team

#------------------------------------------------------------------------------
#!/usr/bin/env python


# imports of S3Upload module
import sys
import os

import mmap
from datetime import datetime
import threading
import time

import argparse
# ends

# enum error codes
eOK = 0
eFAIL = 1
# ends

# user hsh const
USR_ARG_UPLOAD = 'upload'
USR_ARG_DEL = 'del'
# ends

# const node-names in the config file
COUT_S3_PARENTFOLDER = 'Out_S3_ParentFolder'
COUT_S3_UPLOAD = 'Out_S3_Upload'
CIN_S3_PARENTFOLDER = 'In_S3_ParentFolder'
# ends

# const
CCFG_FILE = 'OptimizeRasters.xml'
CCFG_GDAL_PATH = 'GDALPATH'
# ends

# global dbg flags
CS3_MSG_DETAIL = False
CS3_UPLOAD_RETRIES = 3
# ends

# S3Storage direction
CS3STORAGE_IN = 0
CS3STORAGE_OUT = 1
# ends

# classes of S3Upload module to merge as a single source.

class S3Upload:
    def __init__(self):
        pass;

    def run(self, bobj, fobj, id):
        fobj.seek(0)
        if (CS3_MSG_DETAIL == True):
            Message ('Starting (%d)' % (id));
        bobj.upload_part_from_file(fobj, id)
        if (CS3_MSG_DETAIL == True):
            Message ('Done (%d)' % (id));
        fobj.close()
        del fobj


class S3Upload_:
    def __init__(self, s3_bucket, s3_path, local_file):
        self.m_s3_path =  s3_path
        self.m_local_file = local_file
        self.m_s3_bucket = s3_bucket
        pass;

    def init(self):
        # multip-upload test
        try:
            self.mp = self.m_s3_bucket.initiate_multipart_upload(self.m_s3_path, policy='public-read')
        except Exception as exp:
            Message ('Err: (%s)' % (str(exp)), const_critical_text)
            return False
        return True
        # ends

    def upload(self):
        # read in big-file in chunk
        CHUNK_MIN_SIZE = 5242880
##        if (self.m_local_file.endswith('.lrc')):
##            return False
        Message ('[S3-Push] %s..' % (self.m_local_file))

        f = None
        try:         # see if we can open it
            f = open (self.m_local_file, 'rb')
            buff = CHUNK_MIN_SIZE
            fbuff = []

            while True:
                chunk = f.read(buff)
                if not chunk: break
                fbuff.append(SlnTMStringIO(buff))
                fbuff[len(fbuff) - 1].write(chunk)

        except Exception as exp:
            Message ('Err: (%s)' % (str(exp)), const_critical_text)
            return False
        finally:
            if (f is not None):
                f.close()

        idx = 1
        threads = []

        s3upl = S3Upload();

        if (CS3_MSG_DETAIL):
            Message ('Creating (%d) worker(s)..' % (len(fbuff)));
        try:
            for e in fbuff:
                t = threading.Thread(target = s3upl.run, args = (self.mp, e, idx))
                t.daemon = True
                t.start()
                threads.append(t)
                idx += 1
            if (CS3_MSG_DETAIL):
                Message ('\nUploading..')

            for t in threads:
                t.join()
            self.mp.complete_upload()
        except Exception as exp:
            Message ('Err: (%s)' % (str(exp)), const_critical_text)
            self.mp.cancel_upload()
            return False
        finally:
            pass
        return True

    def __del__(self):
        if (self.mp is not None):
            self.mp = None


class SlnTMStringIO:
    def __init__(self, size, buf = ''):
        self.m_size = size
        self.m_buff= mmap.mmap(-1, self.m_size)
        self.m_spos = self.m_fsize = 0

    def close(self):
        self.m_buff.close()
        del self.m_buff
        pass

    def next(self):
        pass

    def seek(self, pos, mode = 0):
        if mode == 1:
            pos += self.m_spos
        elif mode == 2:
            pos += len(self.m_buff)
        self.m_spos = max(0, pos)

    def tell(self):
        return self.m_spos

    def read(self, n = -1):

        buff_len = self.m_fsize

        nRead = (self.m_spos + n)
        if (nRead > buff_len):
            n = n - (nRead - buff_len)

        self.m_buff.seek(self.m_spos, 0)
        self.m_spos += n

        return str(self.m_buff.read(n))

    def readline(self, length=None):
        pass
    def readlines(self, sizehint = 0):
        pass

    def truncate(self, size=None):
        pass
    def write(self, s):
        self.m_buff.write(s)
        self.m_fsize += len(s)
        pass
    def writelines(self, iterable):
        pass
    def flush(self):
        pass
    def getvalue(self):
        pass



class S3Storage:
    def __init__(self):
        pass

    def init(self, remote_path, s3_key, s3_secret, direction, user_config = None):
        self.m_user_config = None
        self.__m_failed_upl_lst = {}

        if (user_config != None):
            self.m_user_config = user_config
        self.CAWS_ACCESS_KEY_ID = s3_key
        self.CAWS_ACCESS_KEY_SECRET = s3_secret

        self.m_bucketname = ''         # no default bucket-name
        if (self.m_user_config is not None):
            s3_bucket = self.m_user_config.getValue('Out_S3_Bucket' if direction == CS3STORAGE_OUT else 'In_S3_Bucket', False)
            if (s3_bucket is not None):
                self.m_bucketname = s3_bucket
            # setup s3 connection
            if (self.m_user_config.getValue(CCFG_PRIVATE_INC_BOTO) == True):    # return type is a boolean hence not need to explicitly convert.
                con = boto.connect_s3(self.CAWS_ACCESS_KEY_ID, self.CAWS_ACCESS_KEY_SECRET)
                self.bucketupload = con.get_bucket(self.m_bucketname, False, None)
            # ends

        self.remote_path = remote_path.replace("\\","/")
        if (self.remote_path[-1:] != '/'):
            self.remote_path += '/'
        return True

    @property
    def inputPath(self):
        return self.__m_input_path

    @inputPath.setter
    def inputPath(self, value):
        self.__m_input_path = value

    def getFailedUploadList(self):
        return self.__m_failed_upl_lst;

    # code to iterate a S3 bucket/folder
    def getS3Content(self, prefix, cb = None, precb = None):
        keys =  self.bucketupload.list(prefix)
        root_only = True
        if (self.m_user_config is not None):
            root_only_ = self.m_user_config.getValue('IncludeSubdirectories')
            if (root_only_ is not None):    # if there's a value, take it else defaults to (True)
                root_only = getBooleanValue(root_only_)
        for key in keys:
            if (key.name.endswith('/') == False):
                if (not root_only == True):
                    if (os.path.dirname(key.name) != os.path.dirname(self.remote_path)):
                        continue
                if (cb is not None):
                    if (precb is not None):
                        if (precb(key.name.replace(self.remote_path, ''), self.remote_path, self.inputPath) == True):     # if raster/exclude list, do not proceed.
                            if (getBooleanValue(self.m_user_config.getValue('istempinput')) == False):
                                continue
                    cb(key, key.name)       # callback on the client-side
        return True
    # ends

    # code to deal with s3-local-cpy
    def S3_copy_to_local(self, S3_key, S3_path):
        err_msg_0 = 'S3/Local path is invalid'
        if (S3_key is None):   # get rid of invalid args.
                Message(err_msg_0)
                return False

        if (self.m_user_config is None):     # shouldn't happen
            Message ('Err: Intenal/User config not initialized.', const_critical_text)
            return False
        input_path = self.m_user_config.getValue(CCFG_PRIVATE_OUTPUT) + S3_path
        if ((self.m_user_config.getValue('istempoutput')) == True):
            input_path = self.m_user_config.getValue('tempoutput', False) + S3_path  # -tempoutput must be set with -s3input=true
        is_raster = False
        (f, e) = os.path.splitext(S3_path)
        is_tmp_input = getBooleanValue(cfg.getValue('istempinput'))

        if ((e[1:] in self.m_user_config.getValue('ExcludeFilter')) == True or
            S3_path.lower().endswith('aux.xml') == True):
            return False
        elif (e[1:] in self.m_user_config.getValue(CCFG_RASTERS_NODE)):
            if (is_tmp_input == True):
                input_path = self.m_user_config.getValue('tempinput', False) + S3_path
                is_raster = True
        if (self.m_user_config.getValue('Pyramids') == CCMD_PYRAMIDS_ONLY):
            return False

        is_cpy_to_s3 = getBooleanValue(cfg.getValue(COUT_S3_UPLOAD))
        mk_path =  input_path.replace('\\', '/').replace(self.remote_path, '')
        Message ('[S3-Pull] %s' % (mk_path))

        flr = os.path.dirname(mk_path)
        if (os.path.exists(flr) == False):
            try:
                os.makedirs(flr)
            except Exception as exp:
                Message ('Err: (%s)' % (str(exp)), const_critical_text)
                return False
        #if (is_raster):
        #    return True
        # let's write remote to local
        fout = None
        try:
            fout = open(mk_path, 'wb')        # can we open for output?
            fout.write(S3_key.read())
            fout.flush()
        except Exception as exp:
            Message ('(%s)' % (str(exp)), const_critical_text);
            return False
        finally:
            if (fout is not None):
                fout.close()
        # ends

        # Handle any post-processing, if the final destination is to S3, upload right away.
        if (is_cpy_to_s3 == True):
            if (getBooleanValue(cfg.getValue('istempinput')) == True):
                if (is_raster == True):
                    return True
            if (S3Upl(mk_path, user_args_Callback) == False):
                return False
        # ends
        return True
    # ends


    def upload(self):
        Message ('[S3-Push]..');
        for r,d,f in os.walk(self.inputPath):

            for file in f:
                lcl_file = os.path.join(r, file).replace('\\', '/')
                ##if (lcl_file.endswith('.lrc')):
                ##    continue
                upl_file = lcl_file.replace(self.inputPath, self.remote_path)
                Message (upl_file)
                # ends
                try:
                    S3 = S3Upload_(self.bucketupload, upl_file, lcl_file);
                    if (S3.init() == False):
                        Message ('Unable to initialize [S3-Push] for (%s=%s)' % (lcl_file, upl_file), const_warning_text)
                        continue
                    ret = S3.upload()
                    if (ret == False):
                        Message ('[S3-Push] (%s)' % (upl_file), const_warning_text)
                        continue
                except Exception as inf:
                    Message ('(%s)' % (str(inf)), const_warning_text)
                finally:
                    if (S3 is not None):
                        del S3
        return True


    def upload_group(self, input_source, single_upload = False):
        m_input_source = input_source.replace('\\', '/')
        input_path = os.path.dirname(m_input_source)
        upload_buff = []

        (p, e) = os.path.splitext(m_input_source)
        for r,d,f in os.walk(input_path):

            for file in f:
                mk_path = os.path.join(r, file).replace('\\', '/')
                if (mk_path.startswith(p)):
                    if (single_upload == True):
                        if (mk_path != m_input_source):
                            continue
                    try:
                        S3 = None
                        upl_file = mk_path.replace(self.inputPath, self.remote_path)
                        if (getBooleanValue(self.m_user_config.getValue('Out_S3_Upload')) == True):
                            rep = self.inputPath
                            if (rep.endswith('/') == False):
                                rep += '/'
                            if (getBooleanValue(self.m_user_config.getValue('istempoutput')) == True):
                                rep = self.m_user_config.getValue('tempoutput')
                            upl_file = mk_path.replace(rep, self.remote_path if cfg.getValue('iss3') == True else self.m_user_config.getValue(CCFG_PRIVATE_OUTPUT, False))
                        S3 = S3Upload_(self.bucketupload, upl_file, mk_path);
                        if (S3.init() == False):
                            Message ('Err: Unable to initialize S3-Upload for (%s=%s)' % (mk_path, upl_file), const_warning_text)
                            continue
                        upl_retries = CS3_UPLOAD_RETRIES
                        ret  = False
                        while(upl_retries and ret == False):
                            ret = S3.upload()
                            if (ret == False):
                                time.sleep(10)   # let's sleep for a while until s3 kick-starts
                                upl_retries -= 1
                                Message ('Err: [S3-Push] (%s), retries-left (%d)' % (upl_file, upl_retries), const_warning_text)
                        if (ret == False):
                            if (not 'upl' in  self.__m_failed_upl_lst):
                                self.__m_failed_upl_lst['upl'] = []
                            exists_ = False
                            for v in self.__m_failed_upl_lst['upl']:
                                if (v['local'] == mk_path):
                                    exists_ = True
                                    break
                            if (not exists_):
                                self.__m_failed_upl_lst['upl'].append({'local' : mk_path, 'remote' : upl_file})
                            if (S3 is not None):
                                del S3
                                S3 = None
                            continue
                    except Exception as inf:
                        Message ('Err: (%s)' % (str(inf)), const_critical_text)
                    finally:
                        if (S3 is not None):
                            del S3
                            S3 = None
                    upload_buff.append(mk_path);    # successful entries to return.
                    if (single_upload == True):
                        return upload_buff

            return upload_buff       # this could be empty.
# ends


from xml.dom import minidom
import os
import sys
import subprocess
from datetime import datetime
import shutil
import threading
import time

import argparse


CIDX_USER_CONFIG  = 2
CCFG_BLOCK_SIZE = 512
CCMD_PYRAMIDS_ONLY = 'only'
CCFG_THREADS = 10
CCFG_RASTERS_NODE = 'RasterFormatFilter'
CCFG_EXCLUDE_NODE = 'ExcludeFilter'
CCFG_PRIVATE_INC_BOTO = '__inc_boto__'
CCFG_PRIVATE_OUTPUT = '__output__'
CCFG_INTERLEAVE = 'Interleave'

raster_buff = []

# log status
const_general_text = 0
const_warning_text = 1
const_critical_text = 2
const_status_text = 3
# ends

def Message(msg, status=0):
    if (log is not None):
        log.Message(msg, status)
    else:
        print (msg)
    sys.stdout.flush()      # for any paprent processes to receive the stdout realtime.


def args_Callback(args, user_data = None):
    m_compression = 'lerc'  # default if external config is faulty
    m_lerc_prec = 0.5
    m_compression_quality = 85
    m_bsize = CCFG_BLOCK_SIZE
    m_mode = 'chs'
    m_nodata_value = None

    if (user_data is not None):
        try:
            compression_ = user_data[CIDX_USER_CONFIG].getValue('Compression')
            if (compression_ is not None):
                m_compression = compression_
            compression_quality_ = user_data[CIDX_USER_CONFIG].getValue('Quality')
            if (compression_quality_ is not None):
                m_compression_quality = compression_quality_
            bsize_ = user_data[CIDX_USER_CONFIG].getValue('BlockSize')
            if (bsize_ is not None):
                m_bsize = bsize_
            lerc_prec_ = user_data[CIDX_USER_CONFIG].getValue('LERCPrecision')
            if (lerc_prec_ is not None):
                m_lerc_prec = lerc_prec_
            m_nodata_value = user_data[CIDX_USER_CONFIG].getValue('NoDataValue')
            m_mode = user_data[CIDX_USER_CONFIG].getValue('Mode')
            m_interleave = user_data[CIDX_USER_CONFIG].getValue(CCFG_INTERLEAVE)
            if (m_interleave is not None):
                m_interleave = m_interleave.upper()
            mode_ = m_mode.split('_')
            if (len(mode_) > 1):
                m_mode = mode_[0]      # mode/output
                m_compression = mode_[1]     # compression
            if (m_mode == 'tif' or
                m_mode == 'tiff'):
                    m_mode = 'GTiff'   # so that gdal_translate'd understand.

        except: # could throw if index isn't found
            pass    # ingnore with defaults.

    args.append ('-of')
    args.append (m_mode)
    args.append ('-co')
    args.append ('COMPRESS=%s' % (m_compression))
    if (m_nodata_value is not None):
        args.append ('-a_nodata')
        args.append (str(m_nodata_value))
    if (m_compression == 'jpeg'):
        args.append ('-co')
        if (m_mode == 'mrf'):   # if the output is (mrf)
            args.append ('QUALITY=%s' % (m_compression_quality))
        else:
            args.append ('JPEG_QUALITY=%s' % (m_compression_quality))
        args.append ('-co')
        args.append ('INTERLEAVE=%s' % (m_interleave))
    if (m_compression == 'lerc'):
        args.append ('-co')
        args.append ('OPTIONS=LERC_PREC=%s' % (m_lerc_prec))
    args.append ('-co')
    args.append ('BLOCKSIZE=%s' % (m_bsize))
    return args


def args_Callback_for_meta(args, user_data = None):
    m_scale = 2
    m_bsize = CCFG_BLOCK_SIZE
    m_pyramid = True
    m_comp = 'lerc'
    m_lerc_prec = 0.5
    m_compression_quality = 85
    if (user_data is not None):
        try:
            scale_ = user_data[CIDX_USER_CONFIG].getValue('Scale')
            if (scale_ is not None):
                m_scale = scale_
            bsize_ = user_data[CIDX_USER_CONFIG].getValue('BlockSize')
            if (bsize_ is not None):
                m_bsize = bsize_
            ovrpyramid = user_data[CIDX_USER_CONFIG].getValue('isuniformscale')
            if (ovrpyramid is not None):
                m_pyramid = ovrpyramid
            py_comp = user_data[CIDX_USER_CONFIG].getValue('Compression')
            if (py_comp is not None):
                m_comp = py_comp
            compression_quality_ = user_data[CIDX_USER_CONFIG].getValue('Quality')
            if (compression_quality_ is not None):
                m_compression_quality = compression_quality_
            m_interleave = user_data[CIDX_USER_CONFIG].getValue(CCFG_INTERLEAVE)
            if (m_interleave is not None):
                m_interleave = m_interleave.upper()
            lerc_prec = user_data[CIDX_USER_CONFIG].getValue('LERCPrecision')
            if (lerc_prec is not None):
                m_lerc_prec = lerc_prec
        except:     # could throw if index isn't found
            pass    # ingnore with defaults.

    args.append ('-of')
    args.append ('MRF')
    args.append ('-co')
    args.append ('COMPRESS=%s' % (m_comp))
    if (m_comp == 'lerc'):
        args.append ('-co')
        args.append ('OPTIONS=LERC_PREC=%s' % (m_lerc_prec))
    elif(m_comp == 'jpeg'):
        args.append ('-co')
        args.append ('QUALITY=%s' % (m_compression_quality))
        args.append ('-co')
        args.append ('INTERLEAVE=%s' % (m_interleave))
    args.append ('-co')
    args.append ('NOCOPY=True')
    if (m_pyramid == True):
        args.append ('-co')
        args.append ('UNIFORM_SCALE=%s' % (m_scale))
    args.append ('-co')
    args.append ('BLOCKSIZE=%s' % (m_bsize))
    args.append ('-co')
    # let's fix the cache extension
    cache_source = user_data[0]
    args.append ('CACHEDSOURCE=%s' % (cache_source))
    # ends
    return args


def copy_callback(file, src, dst):
    Message(file)
    return True

def exclude_callback(file, src, dst):
    if (file is None):
        return False
    (f, e) = os.path.splitext(file)
    if (e[1:] in cfg.getValue(CCFG_RASTERS_NODE)):
        raster_buff.append({'f' : file, 'src' : src, 'dst' : dst})
        return True
    return False

def exclude_callback_for_meta(file, src, dst):
    exclude_callback (file, src, dst)


class Copy:
    def __init__(self):
        pass

    def init(self, src, dst, copy_list, cb_list, user_config = None):
        self.src= src.replace('\\', '/')
        if (self.src[-1:] != '/'):
            self.src += '/'

        self.dst = dst.replace('\\', '/')
        if (self.dst[-1:] != '/'):
            self.dst += '/'
        self.format = copy_list
        self.cb_list = cb_list

        self.m_user_config = None
        self.__m_include_subs = True

        if (user_config != None):
            self.m_user_config = user_config
            include_subs = self.m_user_config.getValue('IncludeSubdirectories')
            if (include_subs is not None):    # if there's a value, take it else defaults to (True)
                self.__m_include_subs = getBooleanValue(include_subs)

        return True

    def processs(self, post_processing_callback = None, post_processing_callback_args = None, pre_processing_callback = None):

        CONST_EXT_AUX_XML = 'aux.xml'
        CONST_EXT_AUX_XML_LEN = len(CONST_EXT_AUX_XML)

        if (log is not None):
            log.CreateCategory('Copy')
        Message('Copying non rasters/aux files (%s=>%s)..' % (self.src, self.dst))

        for r,d,f in os.walk(self.src):
            for file in f:
                if (self.__m_include_subs == False):
                    if ((r[:-1] if r[-1:] == '/' else r) != os.path.dirname(self.src)):     # note: first arg to walk (self.src) has a trailing '/'
                        continue
                (f_, ext) = os.path.splitext(file)
                extension = ext[1:]
                if (extension == 'xml' and                  # special case-check of the 'xml' extension.
                    file[-CONST_EXT_AUX_XML_LEN:] == CONST_EXT_AUX_XML):
                        extension = CONST_EXT_AUX_XML
                free_pass = False

                dst_path = r.replace(self.src, self.dst)

                if (('*' in self.format['copy']) == True):
                    free_pass = True
                if (free_pass == False and
                    ((extension in self.format['copy']) == False)):
                    continue
                if ((extension in self.format['exclude']) == True):        # skip 'exclude' list items.
                    if (('exclude' in self.cb_list) == True):
                        if (self.cb_list['exclude'] is not None):
                            if (self.m_user_config is not None):
                                if (getBooleanValue(self.m_user_config.getValue('istempoutput')) == True):
                                    dst_path = r.replace(self.src, self.m_user_config.getValue('tempoutput', False))    # no checks on temp-output validty done here. It's assumed it has been prechecked at the time of its assignment.
                            if (self.cb_list['exclude'](file, r, dst_path) == False):       # skip fruther processing if 'false' returned from the call-back fnc
                                continue
                    continue
                try:
                    if (('copy' in self.cb_list) == True):
                        if (self.cb_list['copy'] is not None):
                            if (self.cb_list['copy'](file, r, dst_path) == False):       # skip fruther processing if 'false' returned
                                continue
                    if (os.path.exists(dst_path) == False):
                        os.makedirs(dst_path)

                    dst_file = os.path.join(dst_path, file)
                    src_file = os.path.join(r, file)
                    do_post_processing_cb = do_copy = True
                    if (os.path.dirname(src_file.replace('\\','/')) != os.path.dirname(dst_path.replace('\\', '/'))):
                        if (pre_processing_callback is not None):
                            do_post_processing_cb = do_copy = pre_processing_callback(src_file, dst_file, self.m_user_config)
                        if (do_copy == True):
                             shutil.copyfile(src_file, dst_file)
                             Message ('[CPY] %s' % (src_file.replace(self.src, '')))
                    # copy post-processing
                    if (do_post_processing_cb == True):
                        if (post_processing_callback is not None):
                            ret = post_processing_callback(dst_file, post_processing_callback_args)    # ignore errors from the callback
                    # ends
                except Exception as info:
                    Message ('Err: (%s)' % (str(info)), const_critical_text)
                    continue

        Message('Done.')
        if (log is not None):
            log.CloseCategory()

        return True

    def get_group_filelist(self, input_source):          # static
        m_input_source = input_source.replace('\\', '/')
        input_path = os.path.dirname(m_input_source)
        file_buff = []
        (p, e) = os.path.splitext(m_input_source)
        for r,d,f in os.walk(input_path):
            for file in f:
                mk_path = os.path.join(r, file).replace('\\', '/')
                if (mk_path.startswith(p)):
                    file_buff.append(mk_path)
        return file_buff

    def batch(self, file_lst, args = None,  pre_copy_callback = None):
        threads = []
        files_len = len(file_lst)
        batch = 1
        s = 0
        while 1:
            m = s + batch
            if (m >= files_len):
                m =  files_len

            threads = []

            for i in range(s, m):
                req = file_lst[i]
                (input_file , output_file) = getInputOutput(req['src'], req['dst'], req['f'], isinput_s3)
                dst_path = os.path.dirname(output_file)
                if (os.path.exists(dst_path) == False):
                    os.makedirs(dst_path)
                CCOPY = 0
                CMOVE = 1
                mode_ = CCOPY        # 0 = copy, 1 = move
                if (args is not None):
                    if (isinstance(args, dict) == True):
                        if (('mode' in args) == True):
                            if (args['mode'].lower() == 'move'):
                                mode_ = CMOVE
                if (mode_ == CCOPY):
                    Message ('[CPY] %s' % (output_file))
                    shutil.copyfile(input_file, output_file)
                elif (mode_ == CMOVE):
                    Message ('[MV] %s' % (output_file))
                    shutil.move(input_file, output_file)
            s = m
            if s == files_len or s == 0:
                break
                pass
                # ends
        return True


class compression:

    def __init__(self, gdal_path):
        self.m_gdal_path = gdal_path

        self.CGDAL_TRANSLATE_EXE = 'gdal_translate.exe'
        self.CGDAL_BUILDVRT_EXE = 'gdalbuildvrt.exe'
        self.CGDAL_ADDO_EXE = 'gdaladdo.exe'
        self.m_id = None

    def init(self, user_callback = None, id = None, user_config = None):

        self.m_user_callback = False
        if (user_callback != None):
            self.m_user_callback = True
            self.m_callback = user_callback

        if (id != None):
            self.m_id = id

        if (user_config != None):
            self.m_user_config = user_config

        if (os.path.exists(self.m_gdal_path) == False):
            self.message('Err: Invalid GDAL path (%s)' % (self.m_gdal_path), const_critical_text)
            return False
        msg_text = 'Error: %s is not found at (%s)'
        if (os.path.isfile(os.path.join(self.m_gdal_path, self.CGDAL_TRANSLATE_EXE)) == False):
            self.message(msg_text % (self.CGDAL_TRANSLATE_EXE, self.m_gdal_path))
            return False
        if (os.path.isfile(os.path.join(self.m_gdal_path, self.CGDAL_ADDO_EXE)) == False):
            self.message(msg_text % (self.CGDAL_ADDO_EXE, self.m_gdal_path))
            return False

        return True

    def message(self, msg):
        if (self.m_user_callback == True):
            write = msg
            if (self.m_id != None):
                write = '[%s] %s' % (threading.current_thread().name, msg)
            self.m_callback(write)
        return True

    def buildMultibandVRT(self, input_files, output_file):

        if (len(input_files) ==  0):
            return False

        args = [os.path.join(self.m_gdal_path, self.CGDAL_BUILDVRT_EXE)]
        args.append (output_file)

        for f in (input_files):
            args.append(f)

        self.message('Creating VRT output file (%s)' % (output_file))

        return self.__call_external(args)


    def compress(self, input_file, output_file, args_callback = None, post_processing_callback = None, post_processing_callback_args = None):
        # let's try to make the output dir-tree else GDAL would fail
        out_dir_path = os.path.dirname(output_file)
        if (os.path.exists(out_dir_path) == False):
            try:
                os.makedirs(os.path.dirname(output_file))
            except Exception as exp:
                time.sleep(2)    # let's try to sleep for few seconds and see if any other thread has created it.
                if (os.path.exists(out_dir_path) == False):
                    Message ('Err: (%s)' % str(exp), const_critical_text)
                    return False
        # ends

        do_pyramids = self.m_user_config.getValue('Pyramids')
        if (do_pyramids != CCMD_PYRAMIDS_ONLY):
            args = [os.path.join(self.m_gdal_path, self.CGDAL_TRANSLATE_EXE)]
            if (args_callback is None):      # defaults
                args.append ('-of')
                args.append ('MRF')
                args.append ('-co')
                args.append ('COMPRESS=LERC')
                args.append ('-co')
                args.append ('BLOCKSIZE=512')
            else:
                args = args_callback(args, [input_file, output_file, self.m_user_config])      # callback user function to get arguments.

            args.append (input_file)
            args.append (output_file)

            self.message('Applying compression (%s)' % (input_file))
            ret = self.__call_external(args)
            self.message('Status: (%s).' % ('OK' if ret == True else 'FAILED'))
            if (ret == False):
                return ret

        post_process_output = output_file
        if (do_pyramids == 'true' or
            do_pyramids == CCMD_PYRAMIDS_ONLY):
            iss3 = self.m_user_config.getValue('iss3')
            if (iss3 == True):
                if (do_pyramids != CCMD_PYRAMIDS_ONLY):     # s3->(local)->.ovr
                    input_file = output_file
                output_file = output_file + '.__vrt__'
                self.message ('BuildVrt (%s=>%s)' % (input_file, output_file))
                ret = self.buildMultibandVRT([input_file], output_file)
                self.message('Status: (%s).' % ('OK' if ret == True else 'FAILED'))
                if (ret == False):
                    return ret  # we can't proceed if vrt couldn't be built successfully.

            ret = self.createaOverview(output_file)
            self.message('Status: (%s).' % ('OK' if ret == True else 'FAILED'))
            if (ret == False):
                return False

            if (iss3 == True):
                try:
                    os.remove(output_file)      #*.ext__or__ temp vrt file.
                    in_  = output_file + '.ovr'
                    out_ = in_.replace('.__vrt__' + '.ovr', '.ovr')
                    if (os.path.exists(out_) == True):
                        os.remove(out_)         # probably leftover from a previous instance.
                    self.message ('rename (%s=>%s)' % (in_, out_))
                    os.rename(in_, out_)
                except:
                    self.message ('Warning: Unable to rename/remove (%s)' % (output_file))
                    return False

        # call any user-defined fnc for any post-processings.
        if (post_processing_callback is not None):
            if (getBooleanValue(self.m_user_config.getValue('Out_S3_Upload')) == True):
                self.message ('[S3-Push]..');
            ret = post_processing_callback(post_process_output, post_processing_callback_args, {'f' : post_process_output, 'cfg' : self.m_user_config})
            self.message('Status: (%s).' % ('OK' if ret == True else 'FAILED'))
            if (ret == False):
                return ret
        # ends
        return ret


    def createaOverview(self, input_file, isBQA = False):

        # gdaladdo.exe -r mode -ro --config COMPRESS_OVERVIEW LZW --config USE_RRD NO  --config TILED YES input 2 4 8 16 32
        get_mode = self.m_user_config.getValue('Mode')
        if (get_mode is not None):
            if (get_mode == 'cachingmrf' or
                get_mode == 'clonemrf' or
                get_mode == 'splitmrf'):
                    return True

        self.message('Creating pyramid (%s)' % (input_file))
        # let's input cfg values..
        m_py_factor = '2'
        m_py_sampling = 'average'
        py_factor_ = self.m_user_config.getValue('PyramidFactor')
        if (py_factor_ is not None):
            m_py_factor = py_factor_
        py_sampling_ = self.m_user_config.getValue('PyramidSampling')
        if (py_sampling_ is not None):
            m_py_sampling = py_sampling_
        m_py_compression = self.m_user_config.getValue('PyramidCompression')
        args = [os.path.join(self.m_gdal_path, self.CGDAL_ADDO_EXE)]
        args.append ('-r')
        args.append ('nearest' if isBQA else m_py_sampling)
        m_py_quality = self.m_user_config.getValue('Quality')
        m_py_interleave = self.m_user_config.getValue(CCFG_INTERLEAVE)
        if (m_py_compression == 'jpeg' or
            m_py_compression == 'png'):
            if (get_mode.startswith('mrf') == False):
                args.append ('-ro')
            args.append ('--config')
            args.append ('COMPRESS_OVERVIEW')
            args.append (m_py_compression)
##            args.append ('--config')
##            args.append ('PHOTOMETRIC_OVERVIEW')
##            args.append ('YCBCR')
            args.append ('--config')
            args.append ('INTERLEAVE_OVERVIEW')
            args.append (m_py_interleave)
            args.append ('--config')
            args.append ('JPEG_QUALITY_OVERVIEW')
            args.append (m_py_quality)

        args.append (input_file)
        m_ary_factors = m_py_factor.replace(',', ' ').split()
        for f in m_ary_factors:
            args.append (f)

        return self.__call_external(args)



    def __call_external(self, args):

        p = subprocess.Popen(args, creationflags=subprocess.SW_HIDE, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        message = ''
        first_pass_ = True
        messages = []

        bSuccess = False

        while True:
            message = p.stdout.readline()
            if not message:
                break

            if (bSuccess == False):
                if (message.find('100 - done.') >= 0):
                    bSuccess = True

            messages.append(message.strip())


        if (bSuccess == True):
            self.message('messages:')
            for m in messages:
                    self.message(m)

        warnings = p.stderr.readlines()

        if (len(warnings) > 0):
            self.message('warnings:')
            for w in warnings:
                self.message(w.strip())
        else:
            bSuccess = True

        return bSuccess


class Config:
    def __init__(self):
        pass

    def init(self, config, root):
        try:
            self.m_doc = minidom.parse(config)
        except Exception as exp:
            Message ('Err: (%s)' % str(exp), const_critical_text)
            return False

        nodes = self.m_doc.getElementsByTagName(root)
        if (len(nodes) == 0):
            Message ('Warning: search results empty')
            return False

        node = nodes[0].firstChild
        self.m_cfgs = {}

        while (node != None):
            if (node.hasChildNodes() == False):
                node = node.nextSibling
                continue

            if ((node.nodeName in self.m_cfgs) == False):
                self.m_cfgs[node.nodeName] = node.firstChild.nodeValue

            node = node.nextSibling
            pass
        return True

    def getValue(self, key, toLower = True):  # returns (value) or None
        if ((key in self.m_cfgs) == True):
            if (toLower == True):
                try:    # trap any non-strings
                    return self.m_cfgs[key]
                except:
                    pass
            return self.m_cfgs[key]
        return None

    def setValue(self, key, value):
        if (key in self.m_cfgs):
            if (hasattr(self.m_cfgs[key], '__setitem__') == True):
                self.m_cfgs[key].append(value)
                return
        self.m_cfgs[key] = value


def S3Upl(input_file, user_args, *args):
    if (S3_storage is None):    # globally declared: S3_storage
        Message ('Internal error at [S3Upl]', const_critical_text)
        return False

    ret_buff = S3_storage.upload_group(input_file)
    if (len(ret_buff) == 0):
        return False

    if (CS3_MSG_DETAIL == True):
        Message ('Following file(s) uploaded to S3')
        for f in ret_buff:
            Message ('%s' % (f))

    if (user_args != None):
        if (USR_ARG_DEL in user_args):
            if (user_args[USR_ARG_DEL] is not None and
                user_args[USR_ARG_DEL] == True):
                for f in ret_buff:
                    try:
                        os.remove(f)
                        Message ('[Del] %s' % (f))
                    except Exception as exp:
                        Message ('[Del] Err: (%s)' % (str(exp)), const_critical_text)
    return (len(ret_buff) > 0)


def getInputOutput(inputfldr, outputfldr, file, isinput_s3):
    input_file = os.path.join(inputfldr, file)
    output_file = os.path.join(outputfldr, file)
    if (isinput_s3):
        input_file = cfg.getValue('In_S3_Prefix') + input_file
        output_file = outputfldr #  + '/' + inputfldr
        if (getBooleanValue(cfg.getValue('istempinput')) == True or
            getBooleanValue(cfg.getValue('istempoutput')) == True):
            output_file = os.path.join(output_file, file)
            if (getBooleanValue(cfg.getValue('istempinput')) == True):
                input_file = os.path.join(cfg.getValue('tempinput', False), file)   # + inputfldr
            if (getBooleanValue(cfg.getValue('istempoutput')) == True):
                output_file = os.path.join(cfg.getValue('tempoutput', False), file) # + inputfldr
            return (input_file, output_file)
        output_file = os.path.join(output_file, file)
    return (input_file, output_file)


def getBooleanValue(value):
    if (value is None):
        return False
    if (isinstance(value, bool) == True):
        return value
    val = value.lower()
    if (val == 'true' or
        val == 'yes' or
        val == 't' or
        val == '1' or
        val == 'y'):
            return True
    return False

def formatExtensions (value):
    if (value is None or
        len(value.strip()) == 0):
        return []
    frmts = value.split(',')
    for i in range(0, len(frmts)):
        frmts[i] = frmts[i].strip()
    return frmts


# custom exit code block to write out logs
def terminate(exit_code, log_category = False):

    if (log != None):
        success = 'OK'
        if (exit_code != 0):
            success = 'Failed!'
        log.Message(success, log.const_status_text)
        if (log_category == True):
            log.CloseCategory()
        log.WriteLog('#all')   #persist information/errors collected.

    sys.exit(exit_code)
# ends

def fn_pre_process_copy(src, dst, arg):
    g_pre_cpy_list.append({'src' : src, 'dst' : dst})
    return True     # continue with default logic/copying within caller.


def fn_copy_temp_dst(input_source, cb_args, *args):
    fn_cpy_ = Copy()
    file_lst = fn_cpy_.get_group_filelist(input_source)
    if (len(file_lst) == 0):
        return False    # no copying.
    files = []
    for file in file_lst:
        (p, f) = os.path.split(file.replace('\\', '/'))
        if (args is not None):
            if (isinstance(args[0], dict) == True):
                if (('cfg' in args[0]) == True):
                    if (getBooleanValue(args[0]['cfg'].getValue('istempoutput')) == False):
                        return False    # no copying..
                    p += '/'
                    t = args[0]['cfg'].getValue('tempoutput', False).replace('\\', '/')    # safety check
                    if (t.endswith('/') == False): # making sure, replace will work fine.
                        t += '/'
                    o = args[0]['cfg'].getValue(CCFG_PRIVATE_OUTPUT).replace('\\', '/') # safety check
                    if (o.endswith('/') == False):
                        o += '/'
                    dst = (p.replace(t, o))
                    files.append({'src' : p, 'dst' : dst, 'f' : f})

    if (len(files) != 0):
        fn_cpy_.batch(files, {'mode' : 'move'}, None)
    return True


def main():
    pass

if __name__ == '__main__':
    main()

__program_ver__ = 'v3.7c'
__program_name__ = 'RasterOptimize/RO.py %s' % __program_ver__

parser = argparse.ArgumentParser(description='Convert raster formats to a valid output format through GDAL_Translate.\n' +
'\nPlease Note:\nOptimizeRasters.py is entirely case-sensitive, extensions/paths in the config ' +
'file are case-sensitive and the program will fail if the correct paths/case are not ' +
'entered at the cmd-line or in the config file.\n'
)

parser.add_argument('-mode', help='Processing mode/output format', dest='mode');
parser.add_argument('-input', help='Input raster files directory', dest='input_path');
parser.add_argument('-output', help='Output directory', dest='output_path');
parser.add_argument('-cache', help='cache output directory', dest='cache_output_path');
parser.add_argument('-config', help='Configuration file with default settings', dest='input_config');
parser.add_argument('-quality', help='JPEG quality if compression is jpeg', dest='quality_jpeg');
parser.add_argument('-prec', help='LERC precision', dest='precision_lerc');
parser.add_argument('-pyramids', help='Generate pyramids? [true/false/only]', dest='pyramids');
parser.add_argument('-s3input', help='Is -input path on S3? [true/false: default:false]', dest='iss3');
parser.add_argument('-s3output', help='Is -output path on S3? [true/false]', dest='iss3out');
parser.add_argument('-subs', help='Include sub-directories in -input? [true/false]', dest='issubs');
parser.add_argument('-tempinput', help='Path to copy -input raters before conversion', dest='tempinput');
parser.add_argument('-tempoutput', help='Path to output converted rasters before moving to (-output) path', dest='tempoutput');

log  = None
g_pre_cpy_list = []

Message (__program_name__)
Message (parser.description)

args = parser.parse_args()

# read in the config file.
if (args.input_config is None):
    args.input_config = os.path.join(os.path.dirname(__file__), CCFG_FILE)

config_ = args.input_config
cfg  = Config()
ret = cfg.init(config_, 'Defaults')
if (ret == False):
    Message ('Unable to read-in settings from (%s)' % (config_), const_critical_text)
    terminate(eFAIL)
# ends







# fix the slashes to force a convention
if (args.input_path is not None):
    args.input_path = args.input_path.replace('\\', '/')
if (args.output_path is not None):
    args.output_path = args.output_path.replace('\\', '/')
# ends

# read in (interleave)
if (cfg.getValue(CCFG_INTERLEAVE) is None):
    cfg.setValue(CCFG_INTERLEAVE, 'BAND');
# ends

# overwrite (Out_S3_Upload, IncludeSubdirectories) with cmd-line if defined.
if (args.iss3out is not None):
    cfg.setValue(COUT_S3_UPLOAD, getBooleanValue(args.iss3out))
if (args.issubs is not None):
    cfg.setValue('IncludeSubdirectories', getBooleanValue(args.issubs))
# ends


# do we have temp-input-path to copy rasters first before conversion.
is_input_temp = False
if (args.tempinput is not None):
    args.tempinput = args.tempinput.strip().replace('\\', '/')
    if (args.tempinput.endswith('/') == False):
        args.tempinput += '/'
    if (os.path.isdir(args.tempinput) == False):
        try:
            os.makedirs(args.tempinput)
        except Exception as exp:
            Message('Unable to create the temp-input-path (%s) [%s]' % (args.tempinput, str(exp)), const_critical_text)
            terminate(eFAIL)
    is_input_temp = True         # flag flows to deal with temp-input-path
    cfg.setValue('istempinput', is_input_temp)
    cfg.setValue('tempinput', args.tempinput)
# ends

# let's setup output temp path.
is_output_temp = False
if (args.tempoutput is not None):
    args.tempoutput = args.tempoutput.strip().replace('\\', '/')
    if (args.tempoutput.endswith('/') == False):
        args.tempoutput += '/'
    if (os.path.isdir(args.tempoutput) == False):
        # attempt to create the temp-output path
        try:
            os.makedirs(args.tempoutput)
        except Exception as exp:
            Message ('Unable to create the temp-output-path (%s)\n[%s]' % (args.tempoutput, str(exp)), const_critical_text)
            terminate(eFAIL)
        # ends
    is_output_temp = True
    cfg.setValue('istempoutput', is_output_temp)
    cfg.setValue('tempoutput', args.tempoutput)
# ends


#log module
try:
    solutionLib_path = os.path.realpath(__file__)
    if (os.path.isdir(solutionLib_path) == False):
        solutionLib_path = os.path.dirname(solutionLib_path)
    sys.path.append(os.path.join(solutionLib_path, 'solutionsLog'))
    import logger
    log = logger.Logger();

    log.Project ('OptimizeRasters')
    log.LogNamePrefix('RO')
    log.StartLog()

    _CLOG_FOLDER = 'logs'
    log_output_folder  = os.path.join(solutionLib_path, _CLOG_FOLDER)

    cfg_log_path = cfg.getValue('LogPath')
    if (cfg_log_path is not None):
        if (os.path.isdir(cfg_log_path) == False):
            Message ('Invalid log-path (%s). Resetting to (%s)' % (cfg_log_path, log_output_folder));
            cfg_log_path = None

    if (cfg_log_path is not None):
        log_output_folder = os.path.join(cfg_log_path, _CLOG_FOLDER)

    log.SetLogFolder(log_output_folder)
    Message ('Log-path set to (%s)' % (log_output_folder))

except Exception as exp:
    Message ('Warning: External logging support disabled!');
    print (str(exp));
# ends


# let's write to log (input config file content plus all cmd-line args)
if (log is not None):
    # inject cmd-line
    log.CreateCategory('Cmd-line')
    cmd_line  = []
    for arg in str(args).lower().replace('namespace(', '')[:-1].replace('\\\\', '/').split(','):
        try:
            (k, v) = arg.split('=')
        except:
            log.Message('Invalid arg at cmd-line (%s)' % (arg.strip()), const_critical_text)
            continue
        if (v != 'none'):
            cmd_line.append(arg)

    log.Message(' '.join(cmd_line), const_general_text);
    log.CloseCategory()
    # ends

    # inject cfg content
    log.CreateCategory('Input-config-values')
    for v in cfg.m_cfgs:
        log.Message('%s=%s' % (v, cfg.m_cfgs[v]), const_general_text)
    log.CloseCategory()
    # ends
# ends

# are we doing input from S3?
isinput_s3 = getBooleanValue(args.iss3);

# import boto modules only when required. This allows users to run the program for only local file operations.
if (isinput_s3 == True or
    getBooleanValue(cfg.getValue(COUT_S3_UPLOAD)) == True):
    cfg.setValue(CCFG_PRIVATE_INC_BOTO, True)
    try:
        import boto
        from boto.s3.key import Key
        from boto.s3.connection import OrdinaryCallingFormat
    except Exception as exp:
        Message ('\n%s requires the (boto) module to run its S3 specific operations. Please install (boto) for python.' % (__program_name__), const_critical_text)
        terminate(eFAIL)
# ends

# take care of missing -input and -output if -s3input==True
if (isinput_s3 == True):
    if (args.input_path is None):
        args.input_path = cfg.getValue(CIN_S3_PARENTFOLDER, False);
        if (args.input_path is not None):
            args.input_path = args.input_path.strip().replace('\\', '/')
        cfg.setValue(CIN_S3_PARENTFOLDER, args.input_path)

is_s3_upload = getBooleanValue(cfg.getValue(COUT_S3_UPLOAD))
if (is_s3_upload == True):
    if (is_output_temp == False):
        Message ('-tempoutput must be specified if -s3upload=true', const_critical_text)
        terminate(eFAIL)
    if (args.output_path is None):
        args.output_path = cfg.getValue(COUT_S3_PARENTFOLDER, False);
        if (args.output_path is not None):
            args.output_path = args.output_path.strip().replace('\\', '/')
        cfg.setValue(COUT_S3_PARENTFOLDER, args.output_path)
# ends

if (args.output_path is None or
    args.input_path is None):
    Message ('-input/-ouput is not specified!', const_critical_text)
    terminate(eFAIL)

# set output in cfg.
dst_ = args.output_path
if (dst_[-1:] != '/'):
    dst_ += '/'
cfg.setValue(CCFG_PRIVATE_OUTPUT, dst_)
# ends

# cfg-init-valid modes
cfg_modes = {
'tif',
'tif_lzw',
'tif_jpeg',
'tif_mix',
'tif_dg',
'tiff_landsat',
'mrf',
'mrf_jpeg',
'mrf_mix',
'mrf_dg',
'mrf_landsat',
'cachingmrf',
'clonemrf',
'splitmrf'
}
# ends

# read-in (mode)
cfg_mode = args.mode     # cmd-line -mode overrides the cfg value.
if (cfg_mode is None):
    cfg_mode = cfg.getValue('Mode')
if (cfg_mode is None or
    (cfg_mode in cfg_modes) == False):
    Message('<Mode> value not set/illegal', const_critical_text);
    terminate(eFAIL)
cfg.setValue('Mode', cfg_mode)
# ends

# read in build pyramids value
do_pyramids = 'true'
if (args.pyramids is None):
    args.pyramids = cfg.getValue('BuildPyramids')
if (args.pyramids is not None):
    do_pyramids = args.pyramids = args.pyramids.lower()
# ends

# set jpeg_quality from cmd to override cfg value. Must be set before compression->init()
if (args.quality_jpeg is not None):
    cfg.setValue('Quality', args.quality_jpeg)
if (args.precision_lerc is not None):
    cfg.setValue('LERCPrecision', args.precision_lerc)
if (args.pyramids is not None):
    if (args.pyramids == CCMD_PYRAMIDS_ONLY):
        if (args.input_path != args.output_path):
            if (isinput_s3 == True):    # in case of input s3, output is used as a temp folder locally.
                if (getBooleanValue(cfg.getValue(COUT_S3_UPLOAD)) == True):
                    if (cfg.getValue(COUT_S3_PARENTFOLDER) != cfg.getValue(CIN_S3_PARENTFOLDER)):
                        Message ('<%s> and <%s> must be the same if the -pyramids=only' % (CIN_S3_PARENTFOLDER, COUT_S3_PARENTFOLDER), const_critical_text)
                        terminate(eFAIL)
            else:
                Message ('-input and -output paths must be the same if the -pyramids=only', const_critical_text);
                terminate(eFAIL)

if (getBooleanValue(do_pyramids) == False and
    do_pyramids != CCMD_PYRAMIDS_ONLY):
        do_pyramids = 'false'
cfg.setValue('Pyramids', do_pyramids)
cfg.setValue('isuniformscale', True if do_pyramids == CCMD_PYRAMIDS_ONLY else getBooleanValue(do_pyramids))
# ends


# deal with cfg extensions (rasters/exclude list)
rasters_ext_ = cfg.getValue(CCFG_RASTERS_NODE)
if (rasters_ext_ is None):
    rasters_ext_ = 'tif,mrf'        # defaults: in-code if defaults are missing in cfg file.

exclude_ext_ = cfg.getValue(CCFG_EXCLUDE_NODE)
if (exclude_ext_ is None):
    exclude_ext_ = 'ovr,rrd,aux.xml,idx,lrc,mrf_cache,pjp,ppng,pft,pzp' # defaults: in-code if defaults are missing in cfg file.

cfg.setValue(CCFG_RASTERS_NODE, formatExtensions(rasters_ext_))
cfg.setValue(CCFG_EXCLUDE_NODE, formatExtensions(exclude_ext_))
# ends


# read in the gdal_path from config.
gdal_path = cfg.getValue(CCFG_GDAL_PATH)      # note: validity is checked within (compression-mod)
# ends

# set gdal_data enviornment path
gdal_data = os.path.join(os.path.dirname(gdal_path), 'data')
os.environ['GDAL_DATA'] = gdal_data
# ends

comp = compression(gdal_path)
ret = comp.init(Message, 0, user_config = cfg)      # warning/error messages get printed within .init()
if (ret == False):
    Message('Unable to initialize/compression module', const_critical_text);
    terminate(eFAIL)


# s3 upload settings.
s3_output = cfg.getValue(COUT_S3_PARENTFOLDER, False)
s3_id = cfg.getValue('Out_S3_ID', False)
s3_secret = cfg.getValue('Out_S3_Secret', False)

S3_storage = None        # acts global
if (is_s3_upload == True):
    if (s3_output is None or
        s3_id is None or
        s3_secret is None):
            Message ('Empty/Invalid values detected for keys in the (%s) beginning with (S3)' % (config_), const_critical_text)
            terminate(eFAIL)
    # instance of upload storage.
    S3_storage = S3Storage()
    if (args.output_path is not None):
        s3_output = args.output_path
        cfg.getValue(COUT_S3_PARENTFOLDER, s3_output)

    ret =  S3_storage.init(s3_output, s3_id, s3_secret, CS3STORAGE_OUT, cfg)
    if (ret == False):
        Message ('Unable to initialize the S3 upload module!. Quitting..', const_critical_text);
        terminate(eFAIL)
    S3_storage.inputPath = args.output_path
    # ends

user_args_Callback = {
USR_ARG_UPLOAD : getBooleanValue(cfg.getValue(COUT_S3_UPLOAD)),
USR_ARG_DEL : getBooleanValue(cfg.getValue('Out_S3_DeleteAfterUpload'))
}
# ends


cpy = Copy()

list = {
'copy' : {'*'},
'exclude' : {}
}

for i in cfg.getValue(CCFG_RASTERS_NODE) + cfg.getValue(CCFG_EXCLUDE_NODE):
    list['exclude'][i] = ''

is_caching = False
if (cfg_mode == 'clonemrf' or
    cfg_mode == 'splitmrf' or
    cfg_mode == 'cachingmrf'):
    is_caching = True

if (is_caching == True):
    cfg.setValue('istempinput', False)
    cfg.setValue('Pyramids', False)

callbacks = {
#'copy' : copy_callback,
'exclude'  : exclude_callback
}

callbacks_for_meta = {
'exclude'  : exclude_callback_for_meta
}


CONST_CPY_ERR_0 = 'Err: Unable to initialize (Copy) module!'
CONST_CPY_ERR_1 = 'Err: Unable to process input data/(Copy) module!'

CONST_OUTPUT_EXT = '.%s' % ('mrf')

# keep original-source-ext
cfg_keep_original_ext = getBooleanValue(cfg.getValue('KeepExtension'))
cfg_threads = cfg.getValue('Threads')
msg_threads = 'Warning: Thread-count invalid/undefined, resetting to default'
try:
    cfg_threads = int(cfg_threads)   # (None) value is expected
except:
    cfg_threads = -1
if (cfg_threads <= 0 or
    cfg_threads > CCFG_THREADS):
    cfg_threads = CCFG_THREADS
    Message('%s(%s)' % (msg_threads, CCFG_THREADS))
# ends



# let's deal with copying when -input is on s3
if (isinput_s3 == True):
    cfg.setValue('iss3', True);

    in_s3_parent = cfg.getValue(CIN_S3_PARENTFOLDER, False)
    if (args.input_path is not None):        # this will never be (None)
        in_s3_parent = args.input_path       # Note/Warning: S3 inputs/outputs are case-sensitive hence wrong (case) could mean no files found on S3
        cfg.setValue(CIN_S3_PARENTFOLDER, in_s3_parent)

    in_s3_id = cfg.getValue('In_S3_ID', False)
    in_s3_secret = cfg.getValue('In_S3_Secret', False)
    in_s3_bucket = cfg.getValue('In_S3_Bucket', False)

    if (in_s3_parent is None or
        in_s3_id is None or
        in_s3_secret is None or
        in_s3_bucket is None):
            Message ('Invalid/empty value(s) found in node(s) [In_S3_ParentFodler, In_S3_ID, In_S3_Secret, In_S3_Bucket]', const_critical_text)
            terminate(eFAIL)

    in_s3_parent = in_s3_parent.replace('\\', '/')
    if (in_s3_parent[:1] == '/'):
        in_s3_parent = in_s3_parent[1:]
        cfg.setValue(CIN_S3_PARENTFOLDER, in_s3_parent)

    o_S3_storage = S3Storage()
    ret =  o_S3_storage.init(in_s3_parent, in_s3_id, in_s3_secret, CS3STORAGE_IN, cfg)
    if (ret == False):
        Message ('Unable to initialize S3-storage module!. Quitting..', const_critical_text);
        terminate(eFAIL)

    cfg.setValue('In_S3_Prefix', '/vsicurl/' + o_S3_storage.bucketupload.generate_url(0, force_http=True).split('?')[0])
    o_S3_storage.inputPath = args.output_path
    if (o_S3_storage.getS3Content(o_S3_storage.remote_path, o_S3_storage.S3_copy_to_local, exclude_callback) == False):
        Message ('Err: Unable to read S3-Content', const_critical_text);
        terminate(eFAIL)
# =/vsicurl/http://esridatasets.s3.amazonaws.com/
# ends

# control flow if conversions required.
if (is_caching == False):
    if (isinput_s3 == False):
        ret = cpy.init(args.input_path, args.tempoutput if is_output_temp and getBooleanValue(cfg.getValue(COUT_S3_UPLOAD)) else args.output_path, list, callbacks, cfg)
        if  (ret == False):
            Message(CONST_CPY_ERR_0, const_critical_text);
            terminate(eFAIL)
        ret = cpy.processs(S3Upl if is_s3_upload == True else None, user_args_Callback, fn_pre_process_copy if is_input_temp == True else None)
        if (ret == False):
            Message(CONST_CPY_ERR_1, const_critical_text);
            terminate(eFAIL)
        if (is_input_temp == True):
            pass        # no post custom code yet for non-rasters


    files = raster_buff
    files_len = len(files)

    if (files_len):
        if (is_input_temp == True and
            isinput_s3 == False):
            # if the temp-input path is define, we first copy rasters from the source path to temp-input before any conversion.
            Message ('Copying files to temp-input-path (%s)' % (cfg.getValue('tempinput', False)))
            cpy_files_ = []
            for i in range(0, len(files)):
                get_dst_path = cfg.getValue('tempinput', False)
                cpy_files_.append(
                {
                'src' : files[i]['src'],
                'dst' : get_dst_path,
                'f' : files[i]['f']
                })
                files[i]['src'] = get_dst_path
            cpy.batch(cpy_files_, None)

        Message('Converting..');

    a = []
    threads = []

    batch = cfg_threads
    s = 0
    while 1:
        m = s + batch
        if (m >= files_len):
            m =  files_len

        threads = []

        for i in range(s, m):
            req = files[i]
            (input_file , output_file) = getInputOutput(req['src'], req['dst'], req['f'], isinput_s3)
            f, e = os.path.splitext(output_file)
            if (cfg_keep_original_ext == False):
                output_file = output_file.replace(e, CONST_OUTPUT_EXT)
            t = threading.Thread(target = comp.compress, args = (input_file, output_file, args_Callback, S3Upl if is_s3_upload == True else fn_copy_temp_dst if is_output_temp == True and isinput_s3 == False else None, user_args_Callback))
            t.daemon = True
            t.start()
            threads.append(t)

        for t in threads:
            t.join()
        s = m
        if s == files_len or s == 0:
            break

    # let's clean up the input-temp if has been used.

    # ends
# ends


# block to deal with meta-data ops.
if (is_caching == True and
    do_pyramids != CCMD_PYRAMIDS_ONLY):
    Message ('\nProcessing caching operations...')

    # set data, index extension lookup
    extensions_lup = {
    'lerc' : {'data' : 'lrc', 'index' : 'idx' }
    }
    # ends

    if (isinput_s3 == False):
        raster_buff = []
        if (cfg_mode == 'splitmrf'):        # set explicit (exclude list) for mode (splitmrf)
            list['exclude']['idx'] = ''
        ret = cpy.init(args.input_path, args.output_path, list, callbacks_for_meta, cfg)
        if  (ret == False):
            Message(CONST_CPY_ERR_0, const_critical_text);
            terminate(eFAIL)
        ret = cpy.processs()
        if (ret == False):
            Message(CONST_CPY_ERR_1, const_critical_text);
            terminate(eFAIL)

    for req in raster_buff:
        (input_file , output_file) = getInputOutput(req['src'], req['dst'], req['f'], isinput_s3)
        (f, ext) = os.path.splitext(req['f'])
        ext = ext.lower()
        CMRF_EXT = ext
        output_file = output_file.replace(ext, CMRF_EXT)

        # does the input (mrf) have the required associate(s) e.g. (idx) file?
        # This is a simple check to make sure, we're only dealilng with valid (mrf) formats.
        # Note: Below code has been commented until later stage (20150329).
##        idx_file = input_file
##        is_idx_file = False
##        s3_prefix = cfg.getValue('In_S3_Prefix')
##        if (s3_prefix and
##            o_S3_storage and
##            idx_file.startswith(s3_prefix)):
##            idx_file = '%s.idx' % (os.path.splitext(input_file[len(s3_prefix):])[0])
##            for k in o_S3_storage.bucketupload.list(idx_file):
##                is_idx_file = not is_idx_file
##                break
##        else:
##            try:
##                is_idx_file = os.path.exists('%s.idx' % (os.path.splitext(input_file)[0]))
##            except:
##                pass
##        if (not is_idx_file):
##            Message ('%s looks like an invalid/incomplete (MRF) file. Skipping.' % (input_file), const_warning_text)
##            continue
        # ends
        if (cfg_mode != 'splitmrf'):     # uses GDAL utilities
            ret = comp.compress(input_file, output_file, args_Callback_for_meta)
        else:
            try:
                shutil.copyfile(input_file, output_file)
            except Exception as exp:
                Message ('[CPY] %s (%s)' % (input_file, str(exp)))
                continue

        # let's deal with ops if the (cache) folder is defined at the cmd-line
        input_ = output_file.replace('\\', '/').split('/')
        f, e = os.path.splitext(input_[len(input_) - 1])
        if (os.path.exists(output_file) == False):
            continue
        # update .mrf.
        try:
            comp_val =  None         # for (splitmrf)
            with open(output_file, "r") as c:
                content = c.read()
                if (cfg_mode == 'clonemrf'):
                    if (ext != '.tif'):
                        content = content.replace('<Source>', '<Source clone="true">')
                        with open (output_file, "w") as c:
                            c.write(content)
                elif(cfg_mode == 'splitmrf'):
                    CONST_LBL_COMP = '<Compression>'
                    comp_indx = content.find(CONST_LBL_COMP)
                    if (comp_indx != -1):
                        comp_val = content[comp_indx + len(CONST_LBL_COMP): content.find(CONST_LBL_COMP.replace('<', '</'))].lower()

            key = '<Raster>'
            pos = content.find(key)
            if (pos != -1):
                pos += len(key)
                cache_output = os.path.dirname(output_file)
                if (args.cache_output_path is not None):
                    cache_output = args.cache_output_path

                rep_data_file = rep_indx_file = os.path.join(cache_output, '%s.mrf_cache' % (f)).replace('\\', '/')
                if (not comp_val is None):
                    f, e =  os.path.splitext(input_file)
                    if (comp_val in extensions_lup):
                        rep_data_file = '%s.%s' % (f, extensions_lup[comp_val]['data'])
                        rep_indx_file = '%s.%s' % (f, extensions_lup[comp_val]['index'])
                content = content[:pos] + '<DataFile>%s</DataFile>\n<IndexFile>%s</IndexFile>' % (rep_data_file, rep_indx_file) + content[pos:]
                with open (output_file, "w") as c:
                    c.write(content)

        except Exception as exp:
            Message ('Error: Updating (%s) was not successful!\n%s' % (output_file, str(exp)));
        # ends

# do we have failed upload files on list?
if (is_s3_upload):
    failed_upl_lst = S3_storage.getFailedUploadList()
    if (failed_upl_lst):
        Message ('Retry - Failed upload list.', const_general_text);
        for v in failed_upl_lst['upl']:
            Message ('%s' % (v['local']), const_general_text)
        for v in failed_upl_lst['upl']:
            Message ('%s' % (v['local']), const_general_text)
            ret = S3_storage.upload_group(v['local'])
            for r in ret:
                try:
                    Message ('[Del] %s' % (r))
                    os.remove(r)
                except Exception as exp:
                    Message ('[Del] %s (%s)' % (r, str(exp)))
# ends


# let's clean-up rasters @ temp input path
dbg_delete = True
if (dbg_delete == True):
    if (is_input_temp == True and
        is_caching == False):        # if caching is (True), -inputtemp is ignored and no deletion of source @ -input takes place.
        if (len(raster_buff) != 0):
            Message ('Removing input rasters at (%s)' % (cfg.getValue('tempinput', False)))
            for req in raster_buff:
                (input_file , output_file) = getInputOutput(req['src'], req['dst'], req['f'], isinput_s3)
                try:
                    Message ('[Del] %s' % (input_file))
                    os.remove(input_file )
                except Exception as exp:
                    Message ('[Del] %s (%s)' % (input_file, str(exp)))
            Message ('Done.')
# ends


if (len(raster_buff) == 0):
    Message ('Err: No input rasters to process..', const_warning_text);
# ends


Message ('\nDone..')

terminate(eOK)

