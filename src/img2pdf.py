#!/usr/bin/env python2

# Copyright (C) 2012-2014 Johannes 'josch' Schauer <j.schauer at email.de>
#
# This program is free software: you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this program.  If not, see
# <http://www.gnu.org/licenses/>.

__version__ = "0.1.6~git"
default_dpi = 96.0

import re
import sys
import zlib
import argparse
from PIL import Image
from datetime import datetime
from jp2 import parsejp2
try:
    from cStringIO import cStringIO
except ImportError:
    from io import BytesIO as cStringIO

# XXX: Switch to use logging module.
def debug_out(message, verbose=True):
    if verbose:
        sys.stderr.write("D: "+message+"\n")

def error_out(message):
    sys.stderr.write("E: "+message+"\n")

def warning_out(message):
    sys.stderr.write("W: "+message+"\n")

def datetime_to_pdfdate(dt):
    return dt.strftime("%Y%m%d%H%M%SZ")

def parse(cont, indent=1):
    if type(cont) is dict:
        return b"<<\n"+b"\n".join(
            [4 * indent * b" " + k + b" " + parse(v, indent+1)
             for k, v in sorted(cont.items())])+b"\n"+4*(indent-1)*b" "+b">>"
    elif type(cont) is int:
        return str(cont).encode()
    elif type(cont) is float:
        return ("%0.4f"%cont).encode()
    elif isinstance(cont, obj):
        return ("%d 0 R"%cont.identifier).encode()
    elif type(cont) is str or type(cont) is bytes:
        if type(cont) is str and type(cont) is not bytes:
            raise Exception("parse must be passed a bytes object in py3")
        return cont
    elif type(cont) is list:
        return b"[ "+b" ".join([parse(c, indent) for c in cont])+b" ]"
    else:
        raise Exception("cannot handle type %s"%type(cont))

class obj(object):
    def __init__(self, content, stream=None):
        self.content = content
        self.stream = stream

    def tostring(self):
        if self.stream:
            return (
                ("%d 0 obj " % self.identifier).encode() +
                parse(self.content) +
                b"\nstream\n" + self.stream + b"\nendstream\nendobj\n")
        else:
            return ("%d 0 obj "%self.identifier).encode()+parse(self.content)+b" endobj\n"

class pdfdoc(object):

    def __init__(self, version=3, title=None, author=None, creator=None,
                 producer=None, creationdate=None, moddate=None, subject=None,
                 keywords=None, nodate=False):
        self.version = version # default pdf version 1.3
        now = datetime.now()
        self.objects = []

        info = {}
        if title:
            info[b"/Title"] = b"("+title+b")"
        if author:
            info[b"/Author"] = b"("+author+b")"
        if creator:
            info[b"/Creator"] = b"("+creator+b")"
        if producer:
            info[b"/Producer"] = b"("+producer+b")"
        if creationdate:
            info[b"/CreationDate"] = b"(D:"+datetime_to_pdfdate(creationdate).encode()+b")"
        elif not nodate:
            info[b"/CreationDate"] = b"(D:"+datetime_to_pdfdate(now).encode()+b")"
        if moddate:
            info[b"/ModDate"] = b"(D:"+datetime_to_pdfdate(moddate).encode()+b")"
        elif not nodate:
            info[b"/ModDate"] = b"(D:"+datetime_to_pdfdate(now).encode()+b")"
        if subject:
            info[b"/Subject"] = b"("+subject+b")"
        if keywords:
            info[b"/Keywords"] = b"("+b",".join(keywords)+b")"

        self.info = obj(info)

        # create an incomplete pages object so that a /Parent entry can be
        # added to each page
        self.pages = obj({
            b"/Type": b"/Pages",
            b"/Kids": [],
            b"/Count": 0
        })

        self.catalog = obj({
            b"/Pages": self.pages,
            b"/Type": b"/Catalog"
        })
        self.addobj(self.catalog)
        self.addobj(self.pages)

    def addobj(self, obj):
        newid = len(self.objects)+1
        obj.identifier = newid
        self.objects.append(obj)

    def addimage(self, color, width, height, imgformat, imgdata, pdf_x, pdf_y):
        if color == 'L':
            colorspace = b"/DeviceGray"
        elif color == 'RGB':
            colorspace = b"/DeviceRGB"
        elif color == 'CMYK' or color == 'CMYK;I':
            colorspace = b"/DeviceCMYK"
        else:
            error_out("unsupported color space: %s"%color)
            exit(1)

        if pdf_x < 3.00 or pdf_y < 3.00:
            warning_out("pdf width or height is below 3.00 - decrease the dpi")

        # either embed the whole jpeg or deflate the bitmap representation
        if imgformat is "JPEG":
            ofilter = [ b"/DCTDecode" ]
        elif imgformat is "JPEG2000":
            ofilter = [ b"/JPXDecode" ]
            self.version = 5 # jpeg2000 needs pdf 1.5
        else:
            ofilter = [ b"/FlateDecode" ]
        image = obj({
            b"/Type": b"/XObject",
            b"/Subtype": b"/Image",
            b"/Filter": ofilter,
            b"/Width": width,
            b"/Height": height,
            b"/ColorSpace": colorspace,
            # hardcoded as PIL doesn't provide bits for non-jpeg formats
            b"/BitsPerComponent": 8,
            b"/Length": len(imgdata)
        }, imgdata)

        if color == 'CMYK;I':
            # Inverts all four channels
            image.content[b'/Decode'] = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]

        text = ("q\n%0.4f 0 0 %0.4f 0 0 cm\n/Im0 Do\nQ"%(pdf_x, pdf_y)).encode()

        content = obj({
            b"/Length": len(text)
        }, text)

        page = obj({
            b"/Type": b"/Page",
            b"/Parent": self.pages,
            b"/Resources": {
                b"/XObject": {
                    b"/Im0": image
                }
            },
            b"/MediaBox": [0, 0, pdf_x, pdf_y],
            b"/Contents": content
        })
        self.pages.content[b"/Kids"].append(page)
        self.pages.content[b"/Count"] += 1
        self.addobj(page)
        self.addobj(content)
        self.addobj(image)

    def tostring(self):
        # add info as last object
        self.addobj(self.info)

        xreftable = list()

        result = ("%%PDF-1.%d\n"%self.version).encode()

        xreftable.append(b"0000000000 65535 f \n")
        for o in self.objects:
            xreftable.append(("%010d 00000 n \n"%len(result)).encode())
            result += o.tostring()

        xrefoffset = len(result)
        result += b"xref\n"
        result += ("0 %d\n"%len(xreftable)).encode()
        for x in xreftable:
            result += x
        result += b"trailer\n"
        result += parse({b"/Size": len(xreftable), b"/Info": self.info, b"/Root": self.catalog})+b"\n"
        result += b"startxref\n"
        result += ("%d\n"%xrefoffset).encode()
        result += b"%%EOF\n"
        return result

def convert(images, dpi=None, pagesize=(None, None, None), title=None,
            author=None, creator=None, producer=None, creationdate=None,
            moddate=None, subject=None, keywords=None, colorspace=None,
            nodate=False, verbose=False):

    pagesize_options = pagesize[2]

    pdf = pdfdoc(3, title, author, creator, producer, creationdate,
                 moddate, subject, keywords, nodate)

    for imfilename in images:
        debug_out("Reading %s"%imfilename, verbose)
        try:
            rawdata = imfilename.read()
        except AttributeError:
            with open(imfilename, "rb") as im:
                rawdata = im.read()
        im = cStringIO(rawdata)
        try:
            imgdata = Image.open(im)
        except IOError as e:
            # test if it is a jpeg2000 image
            if rawdata[:12] != "\x00\x00\x00\x0C\x6A\x50\x20\x20\x0D\x0A\x87\x0A":
                error_out("cannot read input image (not jpeg2000)")
                error_out("PIL: %s"%e)
                exit(1)
            # image is jpeg2000
            width, height, ics = parsejp2(rawdata)
            imgformat = "JPEG2000"

            # TODO: read real dpi from input jpeg2000 image
            ndpi = (default_dpi, default_dpi)
            debug_out("input dpi = %d x %d" % ndpi, verbose)

            if colorspace:
                color = colorspace
                debug_out("input colorspace (forced) = %s"%(ics))
            else:
                color = ics
                debug_out("input colorspace = %s"%(ics), verbose)
        else:
            width, height = imgdata.size
            imgformat = imgdata.format

            ndpi = imgdata.info.get("dpi", (default_dpi, default_dpi))
            # in python3, the returned dpi value for some tiff images will
            # not be an integer but a float. To make the behaviour of
            # img2pdf the same between python2 and python3, we convert that
            # float into an integer by rounding
            # search online for the 72.009 dpi problem for more info
            ndpi = (int(round(ndpi[0])),int(round(ndpi[1])))
            debug_out("input dpi = %d x %d" % ndpi, verbose)

            if colorspace:
                color = colorspace
                debug_out("input colorspace (forced) = %s"%(color), verbose)
            else:
                color = imgdata.mode
                if color == "CMYK" and imgformat == "JPEG":
                    # Adobe inverts CMYK JPEGs for some reason, and others
                    # have followed suit as well. Some software assumes the
                    # JPEG is inverted if the Adobe tag (APP14), while other
                    # software assumes all CMYK JPEGs are inverted. I don't
                    # have enough experience with these to know which is
                    # better for images currently in the wild, so I'm going
                    # with the first approach for now.
                    if "adobe" in imgdata.info:
                        color = "CMYK;I"
                debug_out("input colorspace = %s"%(color), verbose)

        debug_out("width x height = %d x %d"%(width,height), verbose)
        debug_out("imgformat = %s"%imgformat, verbose)

        if dpi:
            ndpi = dpi, dpi
            debug_out("input dpi (forced) = %d x %d" % ndpi, verbose)
        elif pagesize_options:
            ndpi = get_ndpi(width, height, pagesize)
            debug_out("calculated dpi (based on pagesize) = %d x %d" % ndpi, verbose)

        # depending on the input format, determine whether to pass the raw
        # image or the zlib compressed color information
        if imgformat is "JPEG" or imgformat is "JPEG2000":
            if color == '1':
                error_out("jpeg can't be monochrome")
                exit(1)
            imgdata = rawdata
        else:
            # because we do not support /CCITTFaxDecode
            if color == '1':
                debug_out("Converting colorspace 1 to L", verbose)
                imgdata = imgdata.convert('L')
                color = 'L'
            elif color in ("RGB", "L", "CMYK", "CMYK;I"):
                debug_out("Colorspace is OK: %s"%color, verbose)
            else:
                debug_out("Converting colorspace %s to RGB"%color, verbose)
                imgdata = imgdata.convert('RGB')
                color = imgdata.mode
            img = imgdata.tobytes()
            # the python-pil version 2.3.0-1ubuntu3 in Ubuntu does not have the close() method
            try:
                imgdata.close()
            except AttributeError:
                pass
            imgdata = zlib.compress(img)
        im.close()

        if pagesize_options and pagesize_options['exact'][1]:
            # output size exactly to specified dimensions
            # pagesize[0], pagesize[1] already checked in valid_size()
            pdf_x, pdf_y = pagesize[0], pagesize[1]
        else:
            # output size based on dpi; point = 1/72 inch
            pdf_x, pdf_y = 72.0*width/float(ndpi[0]), 72.0*height/float(ndpi[1])

        pdf.addimage(color, width, height, imgformat, imgdata, pdf_x, pdf_y)

    return pdf.tostring()

def get_ndpi(width, height, pagesize):
    pagesize_options = pagesize[2]

    if pagesize_options and pagesize_options['fill'][1]:
        if width/height < pagesize[0]/pagesize[1]:
            tmp_dpi = 72.0*width/pagesize[0]
        else:
            tmp_dpi = 72.0*height/pagesize[1]
    elif pagesize[0] and pagesize[1]:
        # if both height and width given with no specific pagesize_option,
        # resize to fit "into" page
        if width/height < pagesize[0]/pagesize[1]:
            tmp_dpi = 72.0*height/pagesize[1]
        else:
            tmp_dpi = 72.0*width/pagesize[0]
    elif pagesize[0]:
        # if width given, calculate dpi based on width
        tmp_dpi = 72.0*width/pagesize[0]
    elif pagesize[1]:
        # if height given, calculate dpi based on height
        tmp_dpi = 72.0*height/pagesize[1]
    else:
        tmp_dpi = default_dpi

    return tmp_dpi, tmp_dpi

def positive_float(string):
    value = float(string)
    if value <= 0:
        msg = "%r is not positive"%string
        raise argparse.ArgumentTypeError(msg)
    return value

def valid_date(string):
    # first try parsing in ISO8601 format
    try:
        return datetime.strptime(string, "%Y-%m-%d")
    except ValueError:
        pass
    try:
        return datetime.strptime(string, "%Y-%m-%dT%H:%M")
    except ValueError:
        pass
    try:
        return datetime.strptime(string, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        pass
    # then try dateutil
    try:
        from dateutil import parser
    except ImportError:
        pass
    else:
        try:
            return parser.parse(string)
        except TypeError:
            pass
    # as a last resort, try the local date utility
    try:
        import subprocess
    except ImportError:
        pass
    else:
        try:
            utime = subprocess.check_output(["date", "--date", string, "+%s"])
        except subprocess.CalledProcessError:
            pass
        else:
            return datetime.utcfromtimestamp(int(utime))
    raise argparse.ArgumentTypeError("cannot parse date: %s"%string)

def get_standard_papersize(string):
    papersizes = {
        "11x17"       : "792x792^",     # "792x1224",
        "ledger"      : "792x792^",     # "1224x792",
        "legal"       : "612x612^",     # "612x1008",
        "letter"      : "612x612^",     # "612x792",
        "arche"       : "2592x2592^",   # "2592x3456",
        "archd"       : "1728x1728^",   # "1728x2592",
        "archc"       : "1296x1296^",   # "1296x1728",
        "archb"       : "864x864^",     # "864x1296",
        "archa"       : "648x648^",     # "648x864",
        "a0"          : "2380x2380^",   # "2380x3368",
        "a1"          : "1684x1684^",   # "1684x2380",
        "a2"          : "1190x1190^",   # "1190x1684",
        "a3"          : "842x842^",     # "842x1190",
        "a4"          : "595x595^",     # "595x842",
        "a5"          : "421x421^",     # "421x595",
        "a6"          : "297x297^",     # "297x421",
        "a7"          : "210x210^",     # "210x297",
        "a8"          : "148x148^",     # "148x210",
        "a9"          : "105x105^",     # "105x148",
        "a10"         : "74x74^",       # "74x105",
        "b0"          : "2836x2836^",   # "2836x4008",
        "b1"          : "2004x2004^",   # "2004x2836",
        "b2"          : "1418x1418^",   # "1418x2004",
        "b3"          : "1002x1002^",   # "1002x1418",
        "b4"          : "709x709^",     # "709x1002",
        "b5"          : "501x501^",     # "501x709",
        "c0"          : "2600x2600^",   # "2600x3677",
        "c1"          : "1837x1837^",   # "1837x2600",
        "c2"          : "1298x1298^",   # "1298x1837",
        "c3"          : "918x918^",     # "918x1298",
        "c4"          : "649x649^",     # "649x918",
        "c5"          : "459x459^",     # "459x649",
        "c6"          : "323x323^",     # "323x459",
        "flsa"        : "612x612^",     # "612x936",
        "flse"        : "612x612^",     # "612x936",
        "halfletter"  : "396x396^",     # "396x612",
        "tabloid"     : "792x792^",     # "792x1224",
        "statement"   : "396x396^",     # "396x612",
        "executive"   : "540x540^",     # "540x720",
        "folio"       : "612x612^",     # "612x936",
        "quarto"      : "610x610^",     # "610x780"
    }

    string = string.lower()
    return papersizes.get(string, string)

def valid_size(string):
    # conversion factors from units to points
    units = {
        'in'  : 72.0,
        'cm'  : 72.0/2.54,
        'mm'  : 72.0/25.4,
        'pt' : 1.0
    }

    pagesize_options = {
        'exact'  : ['\!', False],
        'shrink'  : ['\>', False],
        'enlarge' : ['\<', False],
        'fill'    : ['\^', False],
        'percent' : ['\%', False],
        'count'   : ['\@', False],
    }

    string = get_standard_papersize(string)

    pattern = re.compile(r"""
            ([0-9]*\.?[0-9]*)   # tokens.group(1) == width; may be empty
            ([a-z]*)            # tokens.group(2) == units; may be empty
            x
            ([0-9]*\.?[0-9]*)   # tokens.group(3) == height; may be empty
            ([a-zA-Z]*)         # tokens.group(4) == units; may be empty
            ([^0-9a-zA-Z]*)     # tokens.group(5) == extra options
        """, re.VERBOSE)

    tokens = pattern.match(string)

    # tokens.group(0) should match entire input string
    if tokens.group(0) != string:
        msg = ('Input size needs to be of the format AuxBv#, '
            'where A is width, B is height, u and v are units, '
            '# are options.  '
            'You may omit either width or height, but not both.  '
            'Units may be specified as (in, cm, mm, pt).  '
            'You may omit units, which will default to pt.  '
            'Available options include (! = exact ; ^ = fill ; default = into).')
        raise argparse.ArgumentTypeError(msg)

    # temporary list to loop through to process width and height
    pagesize_size = {
        'x' : [0, tokens.group(1), tokens.group(2)],
        'y' : [0, tokens.group(3), tokens.group(4)]
    }

    for key, value in pagesize_size.items():
        try:
            value[0] = float(value[1])
            value[0] *= units[value[2]]     # convert to points
        except ValueError:
            # assign None if width or height not provided
            value[0] = None
        except KeyError:
            # if units unrecognized, raise error
            # otherwise default to pt because units not provided 
            if value[2]:
                msg = "unrecognized unit '%s'." % value[2]
                raise argparse.ArgumentTypeError(msg)

    x = pagesize_size['x'][0]
    y = pagesize_size['y'][0]

    # parse options for resize methods
    if tokens.group(5):
        for key, value in pagesize_options.items():
            if re.search(value[0], tokens.group(5)):
                value[1] = True

    if pagesize_options['fill'][1]:
        # if either width or height is not given, try to fill in missing value
        if not x:
            x = y
        elif not y:
            y = x

    if pagesize_options['exact'][1]:
        if not x or not y:
            msg = ('exact size requires both width and height.')
            raise argparse.ArgumentTypeError(msg)

    if not x and not y:
        msg = ('width and height cannot both be omitted.')
        raise argparse.ArgumentTypeError(msg)

    return (x, y, pagesize_options)

# in python3, the received argument will be a unicode str() object which needs
# to be encoded into a bytes() object
# in python2, the received argument will be a binary str() object which needs
# no encoding
# we check whether we use python2 or python3 by checking whether the argument
# is both, type str and type bytes (only the case in python2)
def pdf_embedded_string(string):
    if type(string) is str and type(string) is not bytes:
        # py3
        pass
    else:
        # py2
        string = string.decode("utf8")
    string = b"\xfe\xff"+string.encode("utf-16-be")
    string = string.replace(b'\\', b'\\\\')
    string = string.replace(b'(', b'\\(')
    string = string.replace(b')', b'\\)')
    return string

def main():
    rendered_papersizes = ""
    for k,v in sorted(papersizes.items()):
        rendered_papersizes += "    %-8s %s\n"%(k,v)

    parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description='''\
Losslessly convert raster images to PDF without re-encoding JPEG and JPEG2000
images. This leads to a lossless conversion of JPEG and JPEG2000 images with
the only added file size coming from the PDF container itself.

Other raster graphics formats are losslessly stored in a zip/flate encoding of
their RGB representation. This might increase file size and does not store
transparency. There is nothing that can be done about that until the PDF format
allows embedding other image formats like PNG. Thus, img2pdf is primarily
useful to convert JPEG and JPEG2000 images to PDF.
''',
            epilog='''\
Colorspace

  Currently, the colorspace must be forced for JPEG 2000 images that are not in
  the RGB colorspace.  Available colorspace options are based on Python Imaging
  Library (PIL) short handles.

    RGB      RGB color
    L        Grayscale
    1        Black and white (internally converted to grayscale)
    CMYK     CMYK color
    CMYK;I   CMYK color with inversion

Paper sizes

  You can specify the short hand paper size names shown in the first column in
  the table below as arguments to the --pagesize and --imgsize options.  The
  width and height they are mapping to is shown in the second column.  Giving
  the value in the second column has the same effect as giving the short hand
  in the first column. Appending ^T (a caret/circumflex followed by the letter
  T) turns the paper size from portrait into landscape. The postfix thus
  symbolizes the transpose. The values are case insensitive.

%s

Fit options

  The img2pdf options for the --fit argument are shown in the first column in
  the table below. The function of these options can be mapped to the geometry
  operators of imagemagick. For users who are familiar with imagemagick, the
  corresponding operator is shown in the second column.  The third column shows
  whether or not the aspect ratio is preserved for that option (same as in
  imagemagick). Just like imagemagick, img2pdf tries hard to preserve the
  aspect ratio, so if the --fit argument is not given, then the default is
  "into" which corresponds to the absence of any operator in imagemagick.

    into    |   | Y | The default. Width and height values specify maximum
            |   |   | values.
   ---------+---+---+----------------------------------------------------------
    fill    | ^ | Y | Width and height values specify the minimum values.
   ---------+---+---+----------------------------------------------------------
    exact   | ! | N | Width and height emphatically given.
   ---------+---+---+----------------------------------------------------------
    shrink  | > | Y | Shrinks an image with dimensions larger than the given
            |   |   | ones.
   ---------+---+---+----------------------------------------------------------
    enlarge | < | Y | Enlarges an image with dimensions smaller than the given
            |   |   | ones.

Examples

  Convert two scans in JPEG format to a PDF document.

    img2pdf --output out.pdf page1.jpg page2.jpg

  Convert a directory of JPEG images into a PDF with printable A4 pages in
  landscape mode. On each page, the photo takes the maximum amount of space
  while preserving its aspect ratio and a print border of 2 cm on the top and
  bottom and 2.5 cm on the left and right hand side.

    img2pdf --output out.pdf --pagesize A4^T --border 2cm:2.5cm *.jpg

  On each A4 page, fit images into a 10 cm times 15 cm rectangle but keep the
  original image size if the image is smaller than that.

    img2pdf --output out.pdf --pagesize A4 --imgsize 10cmx15cm --fit shrink *.jpg

  Prepare a directory of photos to be printed borderless on photo paper with a
  3:2 aspect ratio and rotate each page so that its orientation is the same as
  the input image.

    img2pdf --output out.pdf --pagesize 15cmx10cm --auto-orient *.jpg

  Encode a grayscale JPEG2000 image. The colorspace has to be forced as img2pdf
  cannot read it from the JPEG2000 file automatically.

    img2pdf --output out.pdf --colorspace L input.jp2
'''%rendered_papersizes)

    parser.add_argument(
        'images', metavar='infile', type=str, nargs='+',
        help='''Specifies the input file(s) in any format that can be read by the
        Python Imaging Library (PIL)''')
    parser.add_argument(
        '-v', '--verbose', action="store_true",
        help='Makes the program operate in verbose mode')
    parser.add_argument(
        '-V', '--version', action='version', version='%(prog)s '+__version__,
        help="Prints version information and exits.")

    outargs = parser.add_argument_group(
            title='General output arguments',
            description='')

    outargs.add_argument(
        '-o', '--output', metavar='out', type=argparse.FileType('wb'),
        default=getattr(sys.stdout, "buffer", sys.stdout),
        help='Makes the program output to a file instead of standard output.')
    outargs.add_argument(
        '-C', '--colorspace', metavar='colorspace', type=pdf_embedded_string,
        help='''
Forces the PIL colorspace. See the epilogue for a list of possible values.
Usually the PDF colorspace would be derived from the color space of the input
image. This option overwrites the automatically detected colorspace from the
input image and thus forces a certain colorspace in the output PDF /ColorSpace
property.''')

    outargs.add_argument(
        '-D', '--nodate', action="store_true",
        help='Suppresses timestamps in the output and thus makes the output deterministic.')

    sizeargs = parser.add_argument_group(
        title='Image and page size and layout arguments',
        description='''\

Every input image will be placed on its own page.  The image size is controlled
by the dpi value of the input image or, if unset or missing, the default dpi of
%.2f. By default, each page will have the same size as the image it shows.
Thus, there will be no visible border between the image and the page border by
default. If image size and page size are made different from each other by the
options in this section, the image will always be centered in both dimensions.

The image size and page size can be explicitly set using the --imgsize and
--pagesize options, respectively.  If either dimension of the image size is
specified but the same dimension of the page size is not, then the latter will
be derived from the former using an optional minimal distance between the image
and the page border (given by the --border option) and/or a certain fitting
strategy (given by the --fit option). The converse happens if a dimension of
the page size is set but the same dimension of the image size is not.

Any length value in below options is represented by the meta variable L which
is a floating point value with an optional unit appended (without a space
between them). The default unit is pt (1.0/72 inch) and other allowed units are
cm (centimeter), mm (millimeter), and in (inch).

Any size argument of the format LxL in the options below specifies the width
and height of a rectangle where the first L represents the width and the second
L represents the height with an optional unit following the value as above.
Either width or height may be omitted but in that case the separating x must
still be present. Instead of giving the width and height explicitly, you may
also specify some (case-insensitive) common page sizes such as letter and A4.
See the epilogue at the bottom for a complete list of the valid sizes.
''' % default_dpi)

    sizeargs.add_argument(
            '-S', '--pagesize', metavar='LxL', type=str, #FIXME: type
         help='''
Sets the size of the PDF pages. The short-option is the upper case S because
it is an mnemonic for being bigger than the image size.''')

    sizeargs.add_argument(
            '-s', '--imgsize', metavar='LxL', type=str, #FIXME: type
            help='''
Sets the size of the images on the PDF pages.  In addition, the unit dpi is
allowed which will set the image size as a value of dots per inch.  Instead of
a unit, width and height values may also have a percentage sign appended,
indicating a resize of the image by that percentage. The short-option is the
lower case s because it is an mnemonic for being smaller than the page size.
''')
    sizeargs.add_argument(
            '-b', '--border', metavar='L[:L[:L[:L]]]', type=str, #FIXME: type
            help='''
Specifies the minimal distance between the image border and the PDF page border.
This value Is overwritten by explicit values set by --pagesize or --imgsize.
The value will be used when calculating page dimensions from the image
dimensions or the other way round. One, two, three or four length values can
be given as an argument, separated by colons. One value specifies the border on
all four sides. Two values specify the border on the top/bottom and left/right,
respectively. Three values specify the border on the top, the left/right and
the bottom, respectively. Four values specify the border on the top, right,
bottom and left, respectively. This follows the convention from CSS margin and
padding values.
''')
    sizeargs.add_argument(
         '-f', '--fit', metavar='FIT', type=str,
         help='''

If --imgsize is given, fits the image using these dimensions. Otherwise, fit
the image into the dimensions given by --pagesize.  FIT is one of into, fill,
exact, shrink and enlarge. The default value is "into". See the epilogue at the
bottom for a description of the FIT options.

''')
    sizeargs.add_argument(
            '-a', '--auto-orient', action="store_true",
            help='''
If both dimensions of the page are given via --pagesize, conditionally swaps
these dimensions such that the page orientation is the same as the orientation
given via --imgsize or, if not both image dimensions are given, the same as the
orientation of the input image. If the orientation of a page gets flipped, then
so do the values set via the --border option.
''')

    metaargs = parser.add_argument_group(title='Arguments setting metadata', description='')
    metaargs.add_argument(
        '--title', metavar='title', type=pdf_embedded_string,
        help='Sets the title metadata value')
    metaargs.add_argument(
        '--author', metavar='author', type=pdf_embedded_string,
        help='Sets the author metadata value')
    metaargs.add_argument(
        '--creator', metavar='creator', type=pdf_embedded_string,
        help='Sets the creator metadata value')
    metaargs.add_argument(
        '--producer', metavar='producer', type=pdf_embedded_string,
        help='Sets the producer metadata value')
    metaargs.add_argument(
        '--creationdate', metavar='creationdate', type=valid_date,
        help='Sets the UTC creation date metadata value in YYYY-MM-DD or YYYY-MM-DDTHH:MM or YYYY-MM-DDTHH:MM:SS format or any format understood by python dateutil module or any format understood by `date --date`')
    metaargs.add_argument(
        '--moddate', metavar='moddate', type=valid_date,
        help='Sets the UTC modification date metadata value in YYYY-MM-DD or YYYY-MM-DDTHH:MM or YYYY-MM-DDTHH:MM:SS format or any format understood by python dateutil module or any format understood by `date --date`')
    metaargs.add_argument(
        '--subject', metavar='subject', type=pdf_embedded_string,
        help='Sets the subject metadata value')
    metaargs.add_argument(
        '--keywords', metavar='kw', type=pdf_embedded_string, nargs='+',
        help='Sets the keywords metadata value')

    args = parser.parse_args()

    args.output.write(
        convert(
            args.images, args.dpi, args.pagesize, args.title, args.author,
            args.creator, args.producer, args.creationdate, args.moddate,
            args.subject, args.keywords, args.colorspace, args.nodate,
            args.verbose))

if __name__ == '__main__':
    main()
