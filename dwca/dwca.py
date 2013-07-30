# -*- coding: utf-8 -*-

from tempfile import mkdtemp
from zipfile import ZipFile
from shutil import rmtree
from BeautifulSoup import BeautifulStoneSoup
import io
import os

# TODO: I don't like the fact we don't see this import is from the same
# package...
# Create a top level package so we can clearly show:
# import python_dwca_reader.utils ?
from utils import CommonEqualityMixin


# Two lines are considered equals if both are instances of DwCALine and
# share the same properties
class DwCALine(CommonEqualityMixin):
    # TODO: if core line: display the number of related extension lines ?
    # TODO: test string representation
    def __str__(self):
        txt = "--\n"

        txt += "Rowtype: " + self.rowtype + "\n"

        if self.from_core:
            txt += "Source: Core file\n"
        else:
            txt += "Source: Extension file\n"

        try:
            txt += 'Line ID: ' + self.id + "\n"
        except AttributeError:
            pass

        try:
            txt += 'Core ID: ' + self.core_id + "\n"
        except AttributeError:
            pass

        txt += "Data: " + str(self.data)

        txt += '\n--'
        return txt

    def __init__(self, line, is_core_type, metadata, unzipped_folder=None):
        # line is the raw line data, directly from file
        # is_core is a flag:
        #   if True:
        #        - metadata contains the whole metaxml
        #        - it will also recursively load the related lines
        #          in the 'extensions' attribute (and unzipped_folder
        #          should be provided for this)
        #   else:
        #        - metadata contains only the <extension> section about our
        #          file
        #        - we don't load other lines recursively
        self.from_core = is_core_type
        self.from_extension = not self.from_core

        if self.from_core:
            my_meta = metadata.core
        else:
            my_meta = metadata

        self.rowtype = my_meta['rowtype']

        # fields is a list of the line's content
        line_ending = my_meta['linesterminatedby'].decode("string-escape")
        field_ending = my_meta['fieldsterminatedby'].decode("string-escape")
        fields = line.rstrip(line_ending).split(field_ending)

        # TODO: Consistency chek ?? fields length should be :
        # num of fields described in core_meta + 2 (id and \n)

        # If core, we have an id; if extension a coreid
        # TODO: ensure in the norm this is always true
        if self.from_core:
            self.id = fields[int(my_meta.id['index'])]
        else:
            self.core_id = fields[int(my_meta.coreid['index'])]

        self.data = {}

        for f in my_meta.findAll('field'):
            # if field by default, we can find its value directly in <field>
            # attribute

            # f is a BeautifulSoup object, not a dict
            # => has_key is NOT deprecated here
            if f.has_key('default'):
                self.data[f['term']] = f['default']
            else:
                # else, we have to look in core file
                self.data[f['term']] = fields[int(f['index'])]

        # Core line: we also need to store related (extension) lines in the
        # extensions attribute

        self.extensions = []

        if self.from_core:
            for ext_meta in metadata.findAll('extension'):
                csv = DwCACSVIterator(ext_meta, unzipped_folder)
                for l in csv.lines():
                    tmp = DwCALine(l, False, ext_meta)
                    if tmp.core_id == self.id:
                        self.extensions.append(tmp)


class DwCAReader:
    # Define __enter__ and __exit__ to be used with the 'with' statement
    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def __init__(self, path):
        """Opens the file, reads all metadata and store it in self.meta
        (BeautifulStoneSoup obj.) Also already open the core file so we've
        a file descriptor for further access."""
        self.archive_path = path

        self._unzipped_folder = self._unzip()
        self._metaxml = self._parse_metaxml_file()

        # Load the (scientific) metadata file and store its representation
        # in metadata attribute for future use.
        self.metadata = self._parse_metadata_file()
        self.core_rowtype = self._get_core_type()
        self.extensions_rowtype = self._get_extensions_types()

        self._datafile = DwCACSVIterator(self._metaxml.core,
                                         self._unzipped_folder)

    @property
    #TODO: decide, test and document what we guarantee about ordering
    def lines(self):
        """Get a list containing all (core) lines of the archive"""
        return list(self.each_line())

    def get_line(self, line_id):
        """Get the line whose id is line_id"""
        for line in self.each_line():
            if line.id == str(line_id):
                return line
        else:
            return None

    def _read_additional_file(self, relative_path):
        """Read an additional file in the archive and return its content."""
        path = os.path.join(self._unzipped_folder, relative_path)
        return open(path).read()

    def _create_temporary_folder(self):
        return mkdtemp()[1]

    def _parse_metadata_file(self):
        """Loads the archive (scientific) Metadata file, parse it with
        BeautifulSoup and return its content"""

        # This method should be called only after ._metaxml attribute is set
        # because the name/path to metadat file is stored in the "metadata"
        # attribute of the "archive" tag
        metadata_file = self._get_metadata_filename()
        return self._parse_xml_included_file(metadata_file)

    def _parse_metaxml_file(self):
        """Loads the meta.xml, parse it with BeautifulSoup and return its
        content"""
        return self._parse_xml_included_file('meta.xml')

    def _parse_xml_included_file(self, relative_path):
        """Loads, parse with BeautifulSoup and returns XML file located
        at relative_path"""
        return BeautifulStoneSoup(self._read_additional_file(relative_path))

    def _unzip(self):
        unzipped_folder = self._create_temporary_folder()
        #TODO: check content of file!!!! It may, for example contains
        #absolute path (see zipfile doc)
        ZipFile(self.archive_path, 'r').extractall(unzipped_folder)
        return unzipped_folder

    def close(self):
        self._cleanup_temporary_folder()

    def _cleanup_temporary_folder(self):
        rmtree(self._unzipped_folder, False)

    def _get_core_type(self):
        return self._metaxml.core['rowtype']

    def _get_extensions_types(self):
        return [e['rowtype'] for e in self._metaxml.findAll('extension')]

    def core_contains_term(self, term_url):
        """Takes a tdwg URL as a parameter and check if field exists for
        this concept in the core file"""
        fields = self._metaxml.core.findAll('field')
        for i in fields:
            if i['term'] == term_url:
                return True
        return False  # If we end up there, the term was not found.

    def _get_metadata_filename(self):
        return self._metaxml.archive['metadata']

    #TODO: decide, test and document what we guarantee about ordering
    # We'll have to edit test_lines_property() if we don't guarantee the
    # same order
    def each_line(self):
        self._datafile.reset_line_iterator()
        for line in self._datafile.lines():
            yield DwCALine(line, True, self._metaxml, self._unzipped_folder)


class GBIFResultsReader(DwCAReader):
    # Compared to a standard DwC-A, GBIF results export contains
    # two additional files to give details about IP rights and citations
    # We make them accessible trough two simples properties

    @property
    def citations(self):
        return self._read_additional_file('citations.txt')

    @property
    def rights(self):
        return self._read_additional_file('rights.txt')


# Simple, internal use class used to iterate on a DwcA-enclosed CSV file
# It initializes itself with the <core> or <extension> section of meta.xml
class DwCACSVIterator:
    def __init__(self, metadata_section, unzipped_folder):
        # metadata_section: <core> or <extension> section of metaxml for
        # the file we want to iterate on
        self._metadata_section = metadata_section
        self._unzipped_folder = unzipped_folder

        self._core_fhandler = io.open(self._get_filepath(),
                                      mode='r',
                                      encoding=self._get_encoding(),
                                      newline=self._get_newline_str(),
                                      errors='replace')
        self.reset_line_iterator()

    def lines(self):
        for line in self._core_fhandler:
            self._line_pointer += 1

            if (self._line_pointer <= self._get_lines_to_ignore()):
                continue
            else:
                yield line

    def _get_filepath(self):
        # TODO: Replace by os.path.join
        return (self._unzipped_folder + '/' +
                self._metadata_section.files.location.string)

    def _get_encoding(self):
        return self._metadata_section['encoding']

    def _get_newline_str(self):
        return self._metadata_section['linesterminatedby'].decode("string-escape")

    def reset_line_iterator(self):
        self._core_fhandler.seek(0, 0)
        self._line_pointer = 0

    def _get_lines_to_ignore(self):
        try:
            return int(self._metadata_section['ignoreheaderlines'])
        except KeyError:
            return 0
