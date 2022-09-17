from __future__ import annotations

import os

import nornir_buildmanager.volumemanager as volumemanager
import nornir_shared.checksum


class XFileElementWrapper(volumemanager.XResourceElementWrapper):
    """Refers to a file generated by the pipeline"""

    @property
    def Name(self) -> str:
        if 'Name' not in self.attrib:
            return self._GetAttribFromParent('Name')

        return self.attrib.get('Name', None)

    @Name.setter
    def Name(self, value):
        assert (isinstance(value, str))
        self.attrib['Name'] = value

    @property
    def Type(self) -> str:
        if 'Type' not in self.attrib:
            return self._GetAttribFromParent('Type')

        return self.attrib['Type']

    @Type.setter
    def Type(self, value):
        self.attrib['Type'] = value

    @property
    def Path(self) -> str:
        return self.attrib.get('Path', '')

    @Path.setter
    def Path(self, val):
        self.attrib['Path'] = val
        directory = os.path.dirname(self.FullPath)

        if directory is not None and len(directory) > 0:
            try:
                os.makedirs(directory)
            except (OSError, FileExistsError):
                if not os.path.isdir(directory):
                    raise ValueError(
                        f"{self.__class__}.Path property was set to an existing file or non-directory object {self.FullPath}")

        if hasattr(self, '__fullpath'):
            del self.__dict__['__fullpath']
        return

    def IsValid(self) -> (bool, str):
        """
        Checks that the file exists by attempting to update the validation time
        """

        try:
            self.ValidationTime = self.LastFileSystemModificationTime
        except FileNotFoundError:
            return False, 'File does not exist'

        result = super(XFileElementWrapper, self).IsValid()

        return result

    @classmethod
    def Create(cls, tag, Path, attrib, **extra):
        obj = XFileElementWrapper(tag=tag, attrib=attrib, **extra)
        obj.attrib['Path'] = Path
        return obj

    @property
    def Checksum(self) -> str:
        """Checksum of the file resource when the node was last updated"""
        checksum = self.get('Checksum', None)
        if checksum is None:
            if os.path.exists(self.FullPath):
                checksum = nornir_shared.checksum.FileChecksum(self.FullPath)
                self.attrib['Checksum'] = str(checksum)
                self._AttributesChanged = True

        return checksum
