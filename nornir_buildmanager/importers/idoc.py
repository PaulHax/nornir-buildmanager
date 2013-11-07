import sys
import re
from nornir_imageregistration.io import mosaicfile
from nornir_imageregistration import image_stats
from nornir_shared.images import *
from nornir_shared.histogram import *
from nornir_buildmanager.VolumeManagerETree import *
from nornir_shared.mathhelper import ListMedian
from nornir_shared.files import RemoveOutdatedFile
import logging
from nornir_shared.plot import Histogram as PlotHistogram

from nornir_buildmanager.operations.tile import VerifyTiles


class SerialEMIDocImport(object):

    @classmethod
    def GetSectionInfo(cls, fileName):
        fileName = os.path.basename(fileName)

        # Make sure extension is present in the filename
        [fileName, ext] = os.path.splitext(fileName)

        SectionNumber = -1
        Downsample = 1
        parts = fileName.split("_")
        try:
            SectionNumber = int(parts[0])
        except:
            # We really can't recover from this, so maybe an exception should be thrown instead
            SectionNumber = -1

        try:
            SectionName = parts[1]
        except:
            SectionName = str(SectionNumber)

        # If we don't have a valid downsample value we assume 1
        try:
            DownsampleStrings = parts[2].split(".")
            Downsample = int(DownsampleStrings[0])
        except:
            Downsample = 1

        return [SectionNumber, SectionName, Downsample]

    @classmethod
    def ToMosaic(cls, VolumeObj, InputPath, OutputPath = None, Extension = None, OutputImageExt = None, TileOverlap = None, TargetBpp = None, debug = None):
        '''
        This function will convert an idoc file in the given path to a .mosaic file.
        It will also rename image files to the requested extension and subdirectory.
        TargetBpp is calculated based on the number of bits required to encode the values
        between the median min and max values 
        '''
        if(OutputImageExt is None):
            OutputImageExt = 'png'

        if(Extension is None):
            Extension = 'idoc'

        # Default to the directory above ours if an output path is not specified
        if OutputPath is None:
            OutputPath = os.path.join(InputPath, "..")

        if not os.path.exists(OutputPath):
            os.makedirs(OutputPath)

        logger = logging.getLogger("IDOC Import")

        # VolumeObj = VolumeManager.Load(OutputPath, Create=True)

        # Report the current stage to the user
        prettyoutput.CurseString('Stage', "SerialEM to Mosaic " + str(InputPath))

        SectionNumber = 0

        idocFiles = glob.glob(os.path.join(InputPath, '*.' + Extension))
        if(len(idocFiles) == 0):
            # This shouldn't happen, but just in case
            assert len(idocFiles) > 0, "ToMosaic called without proper target file present in the path: " + str(InputPath)
            return [None, None]

        ParentDir = os.path.dirname(InputPath)
        sectionDir = os.path.basename(InputPath)

        BlockName = 'TEM'
        BlockObj = XContainerElementWrapper('Block', BlockName)
        [addedBlock, BlockObj] = VolumeObj.UpdateOrAddChild(BlockObj)

        # If the directory has spaces in the name, remove them
        sectionDirNoSpaces = sectionDir.replace(' ', '_')
        if(sectionDirNoSpaces != sectionDir):
            sectionDirNoSpacesFullPath = os.path.join(ParentDir, sectionDirNoSpaces)
            shutil.move(InputPath, sectionDirNoSpacesFullPath)

            sectionDir = sectionDirNoSpaces
            InputPath = sectionDirNoSpacesFullPath

        # If the parent directory doesn't have the section number in the name, change it
        ExistingSectionInfo = cls.GetSectionInfo(sectionDir)
        if(ExistingSectionInfo[0] < 0):
            i = 5
#            SectionNumber = SectionNumber + 1
#            newPathName = ('%' + Config.Current.SectionFormat) % SectionNumber + '_' + sectionDir
#            newPath = os.path.join(ParentDir, newPathName)
#            prettyoutput.Log('Moving: ' + InputPath + ' -> ' + newPath)
#            shutil.move(InputPath, newPath)
#
#            InputPath = newPath
#
#            #Run glob again because the dir changes
#            idocFiles = glob.glob(os.path.join(InputPath,'*.idoc'))
        else:
            SectionNumber = ExistingSectionInfo[0]

        prettyoutput.CurseString('Section', str(SectionNumber))

        idocFilePath = idocFiles[0]

        # Check for underscores.  If there is an underscore and the first part is the sectionNumber, then use everything after as the section name
        SectionName = ('%' + Config.Current.SectionFormat) % SectionNumber
        SectionPath = ('%' + Config.Current.SectionFormat) % SectionNumber
        try:
            parts = sectionDir.partition("_")
            if not parts is None:
                if len(parts[2]) > 0:
                    SectionName = parts[2]
        except:
            pass

        sectionObj = SectionNode(SectionNumber,
                                              SectionName,
                                              SectionPath)

        [addedSection, sectionObj] = BlockObj.UpdateOrAddChildByAttrib(sectionObj, 'Number')
        sectionObj.Name = SectionName

        # Create a channel group
        ChannelName = 'TEM'
        channelObj = XContainerElementWrapper('Channel', ChannelName)
        [added, channelObj] = sectionObj.UpdateOrAddChildByAttrib(channelObj, 'Name')

        # See if we can find a notes file...

        TryAddNotes(channelObj, InputPath, logger)
        TryAddLogs(channelObj, InputPath, logger)

        ChannelPath = channelObj.FullPath
        OutputSectionPath = os.path.join(OutputPath, ChannelPath)
        # Create a channel group for the section

        # I started ignoring existing supertile.mosaic files so I could rebuild sections where
        # a handful of tiles were corrupt
        # if(os.path.exists(SupertilePath)):
        #    continue

        FlipList = Config.GetFlipList(ParentDir);
        Flip = SectionNumber in FlipList;

        if(Flip):
            prettyoutput.Log("Found in FlipList.txt, flopping images")

        ImageExt = None

        ImageSize = [0, 0]
        ImageMap = dict()  # Maps the idoc image name to the converted image name

        IDocData = IDoc.Load(idocFilePath)

        assert(hasattr(IDocData, 'PixelSpacing'))
        assert(hasattr(IDocData, 'DataMode'))
        assert(hasattr(IDocData, 'ImageSize'))

        # If there are no tiles... return
        if IDocData.NumTiles == 0:
            prettyoutput.Log("No tiles found in IDoc: " + idocFilePath)
            return

        AddIdocNode(channelObj, idocFilePath, IDocData, logger)

        # Set the scale
        scaleValueInNm = float(IDocData.PixelSpacing) / 10.0
        [added, ScaleObj] = channelObj.UpdateOrAddChild(XElementWrapper('Scale'))

        ScaleObj.UpdateOrAddChild(XElementWrapper('X', {'UnitsOfMeasure' : 'nm',
                                                             'UnitsPerPixel' : str(scaleValueInNm)}))
        ScaleObj.UpdateOrAddChild(XElementWrapper('Y', {'UnitsOfMeasure' : 'nm',
                                                             'UnitsPerPixel' : str(scaleValueInNm)}))

        ImageBpp = None
        if (hasattr(IDocData, 'DataMode')):
            if IDocData.DataMode == 0:
                ImageBpp = 8
            elif IDocData.DataMode == 1:
                ImageBpp = 16
            elif IDocData.DataMode == 6:
                ImageBpp = 16

        if ImageBpp is None:
            # Figure out the bit depth of the input
            tile = IDocData.tiles[0]

            SourceImageFullPath = os.path.join(InputPath, tile.Image)
            ImageBpp = GetImageBpp(SourceImageFullPath)

        if(not ImageBpp is None):
            prettyoutput.Log("Source images are " + str(ImageBpp) + " bits per pixel")
        else:
            prettyoutput.Log("Could not determine source image BPP")
            return

        FilterName = 'Raw' + str(TargetBpp)
        if(TargetBpp is None):
            FilterName = 'Raw'

        # Create a channel for the Raw data
        filterObj = FilterNode(Name = FilterName)
        [added, filterObj] = channelObj.UpdateOrAddChildByAttrib(filterObj, 'Name')
        filterObj.BitsPerPixel = TargetBpp

        SupertileName = 'Stage'
        SupertileTransform = SupertileName + '.mosaic'
        SupertilePath = os.path.join(OutputSectionPath, SupertileTransform)

        # Check to make sure our supertile mosaic file is valid
        RemoveOutdatedFile(idocFilePath, SupertilePath)

        [added, transformObj] = channelObj.UpdateOrAddChildByAttrib(TransformNode(Name = SupertileName,
                                                                         Path = SupertileTransform,
                                                                         Type = 'Stage'),
                                                                         'Path')
 
        [added, PyramidNodeObj] = filterObj.UpdateOrAddChildByAttrib(TilePyramidNode(Type = 'stage',
                                                                            NumberOfTiles = IDocData.NumTiles),
                                                                            'Path')

        LevelPath = Config.Current.DownsampleFormat % 1

        [added, LevelObj] = PyramidNodeObj.UpdateOrAddChildByAttrib(LevelNode(Level=1), 'Downsample')

        # Make sure the target LevelObj is verified
        VerifyTiles(LevelNode=LevelObj)

        InputImagePath = InputPath
        OutputImagePath = os.path.join(OutputSectionPath, filterObj.Path, PyramidNodeObj.Path, LevelObj.Path)

        if not os.path.exists(OutputImagePath):
            os.makedirs(OutputImagePath)

        # Parse the images
        ImageNumber = 0
        ImageMoveRequired = False
        ImageConversionRequired = not ImageBpp == TargetBpp

        SourceFiles = []
        PositionMap = dict()
        MissingInputImage = False

        for tile in IDocData.tiles:

            [ImageRoot, ImageExt] = os.path.splitext(tile.Image)

            ImageExt = ImageExt.strip('.')
            ImageExt = ImageExt.lower()

            # I rename the converted image because I haven't checked how robust viking is with non-numbered images.  I'm 99% sure it can handle it, but I don't want to test now.
            ConvertedImageName = (Config.Current.TileCoordFormat % ImageNumber) + '.' + OutputImageExt

            ImageNumber = ImageNumber + 1

            SourceImageFullPath = os.path.join(InputPath, tile.Image)
            if not os.path.exists(SourceImageFullPath):
                prettyoutput.Log("Could not locate import image: " + SourceImageFullPath)
                
                MissingInputImage = True
                continue

            SourceFiles.append(SourceImageFullPath)

            TargetImageFullPath = os.path.join(OutputImagePath, ConvertedImageName)

            ImageMoveRequired = ImageMoveRequired | (SourceImageFullPath != TargetImageFullPath)
            ImageConversionRequired = ImageConversionRequired | (ImageExt != OutputImageExt)

            # Check to make sure our supertile mosaic file is valid
            RemoveOutdatedFile(SourceImageFullPath, SupertilePath)
            RemoveOutdatedFile(SourceImageFullPath, TargetImageFullPath)

            PositionMap[TargetImageFullPath] = tile.PieceCoordinates[0:2]
            TargetImageExists = os.path.exists(TargetImageFullPath)
            if not TargetImageExists:
                ImageMap[SourceImageFullPath] = TargetImageFullPath

        # Figure out if we have to move or convert images
        if len(ImageMap) == 0:
            ImageConversionRequired = False

        if(ImageConversionRequired):
            Invert = False

            prettyoutput.Log("Collecting mosaic min/max data")

            histogramFullPath = os.path.join(InputPath, 'Histogram.xml')
            (ActualMosaicMin, ActualMosaicMax) = GetMinMaxCutoffs(SourceFiles, histogramFullPath)

            filterObj.attrib['MaxIntensityCutoff'] = str(ActualMosaicMax)
            filterObj.attrib['MinIntensityCutoff'] = str(ActualMosaicMin)

            PyramidNodeObj.NumberOfTiles = IDocData.NumTiles

            # Figure out how many bits are required to encode the values between min and max
            ValueRange = ActualMosaicMax - ActualMosaicMin

            if(TargetBpp > 8):
                TargetBpp = int(math.ceil(math.log(ValueRange, 2)))

            # Figure out the left shift required to erase the top bits
            MaxUsefulHighBit = int(math.ceil(math.log(ActualMosaicMax, 2)))  # Floor because bits are numbered 0-N
            MinUsefulLowBit = (MaxUsefulHighBit - TargetBpp)

            if MinUsefulLowBit < 0:
                MinUsefulLowBit = 0

            # Build a value to AND with
            andValue = 0
            for i in range(MinUsefulLowBit, MaxUsefulHighBit):
                andValue = andValue + pow(2, i)

            nornir_shared.images.ConvertImagesInDict(ImageMap, Flip=Flip, Bpp=TargetBpp, Invert=Invert, bDeleteOriginal=False, MinMax=[ActualMosaicMin, ActualMosaicMax])
            
            for inputImage in ImageMap:
                outputImageFullPath = ImageMap[inputImage]
                if not os.path.exists(outputImageFullPath):
                    logger.warning("Could not convert: " + str(os.path.basename(inputImage)))
                    del PositionMap[outputImageFullPath]
            
            # nornir_shared.Images.ConvertImagesInDict(ImageMap, Flip=Flip, Bpp=TargetBpp, RightLeftShift=RightLeftShift, Invert=Invert, bDeleteOriginal=False)
            # nornir_shared.Images.ConvertImagesInDict(ImageMap, Flip=Flip, Bpp=TargetBpp, RightLeftShift=None, Invert=Invert, bDeleteOriginal=False, MinMax=[MosaicMin, MosaicMax])
        elif(ImageMoveRequired):
            for f in ImageMap:
                shutil.copy(f, ImageMap[f])

        if len(PositionMap) == 0:
            prettyoutput.Log("No tiles could be mapped to a position, skipping import")
            return 
        
        # If we wrote new images replace the .mosaic file
        if ImageConversionRequired or not os.path.exists(SupertilePath) or MissingInputImage:
            # Writing this file indicates import succeeded and we don't need to repeat these steps, writing it will possibly invalidate a lot of downstream data
            # We need to flip the images.  This may be a Utah scope issue, our Y coordinates are inverted relative to the images.  To fix this
            # we flop instead of flip and reverse when writing the coordinates
            mosaicfile.MosaicFile.Write(SupertilePath, Entries=PositionMap, Flip=not Flip, ImageSize=IDocData.ImageSize, Downsample=1);
            MFile = mosaicfile.MosaicFile.Load(SupertilePath)
            
            #Sometimes files fail to convert, when this occurs remove them from the .mosaic
            if MFile.RemoveInvalidMosaicImages(OutputImagePath):
                MFile.Save(SupertilePath)

            transformObj.Checksum = MFile.Checksum


def GetMinMaxCutoffs(listfilenames, histogramFullPath = None):
    MinCutoff = 0.00001
    MaxCutoff = 0.0001
    histogramObj = None
    if not histogramFullPath is None:
        if os.path.exists(histogramFullPath):
            histogramObj = Histogram.Load(histogramFullPath)

    if histogramObj is None:
        Bpp = nornir_shared.images.GetImageBpp(listfilenames[0])
        histogramObj = image_stats.Histogram(listfilenames, Bpp=Bpp, Scale=.125, numBins=2048)

        if not histogramFullPath is None:
            histogramObj.Save(histogramFullPath)

            HistogramImageFullPath = os.path.join(os.path.dirname(histogramFullPath), 'Histogram.png')
            PlotHistogram(histogramFullPath, HistogramImageFullPath, Title="Raw Data Pixel Intensity")

    assert(not histogramObj is None)

    # I am willing to clip 1 pixel every hundred thousand on the dark side, and one every ten thousand on the light
    return histogramObj.AutoLevel(MinCutoff, MaxCutoff)

def AddIdocNode(containerObj, idocFullPath, idocObj, logger):

    # Copy the idoc file to the output directory
    idocPath = os.path.basename(idocFullPath)
    IDocNodeObj = DataNode(Path=idocPath, attrib={'Name' : 'IDoc'})
    containerObj.RemoveOldChildrenByAttrib('Data', 'Name', 'IDoc')
    [added, IDocNodeObj] = containerObj.UpdateOrAddChildByAttrib(IDocNodeObj, 'Name')

    CopiedFileFullPath = os.path.join(containerObj.FullPath, idocPath)
    if not os.path.exists(CopiedFileFullPath):
        if not os.path.exists(containerObj.FullPath):
            os.makedirs(containerObj.FullPath)
        shutil.copyfile(idocFullPath, CopiedFileFullPath)

    # Copy over attributes from the idoc
    for k in idocObj.__dict__.keys():
        v = idocObj.__dict__[k]
        if k[0] == '_':
            continue

        if isinstance(v, list):
            continue

        setattr(IDocNodeObj, k, v)
#        if isinstance(v,str):
#            IDocNodeObj.attrib[k] = v
#        elif isinstance(v,list):
#
#            continue
#        else:
#            IDocNodeObj.attrib[k] = '%g' % v

    # Read the first tile obj, copy over common attributes
    assert(len(idocObj.tiles) > 0)
    tile = idocObj.tiles[0]

    for k in tile.__dict__.keys():
        v = tile.__dict__[k]

        if k[0] == '_':
            continue

        if isinstance(v, list):
            continue

        if k == 'Defocus':
            continue

        setattr(IDocNodeObj, k, v)

#        if isinstance(v,str):
#            IDocNodeObj.attrib[k] = v
#        elif isinstance(v,list):
#            continue
#        else:
#            IDocNodeObj.attrib[k] = '%g' % v

    return added


def TryAddNotes(containerObj, InputPath, logger):
    NotesFiles = glob.glob(os.path.join(InputPath, '*notes*.*'))
    NotesAdded = False
    if len(NotesFiles) > 0:
        for filename in NotesFiles:
            try:
                from xml.sax.saxutils import escape

                NotesFilename = os.path.basename(filename)
                CopiedNotesFullPath = os.path.join(containerObj.FullPath, NotesFilename)
                if not os.path.exists(CopiedNotesFullPath):
                    if not os.path.exists(containerObj.FullPath):
                        os.makedirs(containerObj.FullPath)
                    shutil.copyfile(filename, CopiedNotesFullPath)
                    NotesAdded = True

                with open(filename, 'r') as f:
                    notesTxt = f.read()
                    [base, ext] = os.path.splitext(filename)
                    encoding = "utf-8"
                    ext = ext.lower()
                    notesTxt = notesTxt.encode(encoding)

                    notesTxt = notesTxt.replace('\0', '')

                    if len(notesTxt) > 0:
                        # XMLnotesTxt = notesTxt
                        # notesTxt = notesTxt.encode('utf-8')
                        XMLnotesTxt = escape(notesTxt)

                        # Create a Notes node to save the notes into
                        NotesNodeObj = NotesNode(Text=XMLnotesTxt, SourceFilename=NotesFilename)
                        containerObj.RemoveOldChildrenByAttrib('Notes', 'SourceFilename', NotesFilename)
                        [added, NotesNodeObj] = containerObj.UpdateOrAddChildByAttrib(NotesNodeObj, 'SourceFilename')

                        if added:
                            # Try to copy the notes to the output dir if we created a node
                            if not os.path.exists(CopiedNotesFullPath):
                                shutil.copyfile(filename, CopiedNotesFullPath)

                        NotesNodeObj.text = XMLnotesTxt
                        NotesNodeObj.encoding = encoding

                        NotesAdded = NotesAdded or added

            except:
                (etype, evalue, etraceback) = sys.exc_info()
                prettyoutput.Log("Attempt to include notes from " + filename + " failed.\n" + evalue.message)
                prettyoutput.Log(etraceback)

    return NotesAdded


def TryAddLogs(containerObj, InputPath, logger):
    '''Copy log files to output directories, and store select meta-data in the containerObj if it exists'''
    LogsFiles = glob.glob(os.path.join(InputPath, '*.log'))
    LogsAdded = False
    if len(LogsFiles) > 0:
        for filename in LogsFiles:

            NotesFilename = os.path.basename(filename)
            CopiedLogsFullPath = os.path.join(containerObj.FullPath, NotesFilename)
            if not os.path.exists(CopiedLogsFullPath):
                if not os.path.exists(containerObj.FullPath):
                    os.makedirs(containerObj.FullPath)
                shutil.copyfile(filename, CopiedLogsFullPath)
                LogsAdded = True

            # OK, try to parse the logs
            try:
                LogData = SerialEMLog.Load(filename)
                if LogData is None:
                    pass

                # Create a Notes node to save the logs into
                LogNodeObj = DataNode(Path=NotesFilename, attrib={'Name':'Log'})
                containerObj.RemoveOldChildrenByAttrib('Data', 'Name', 'Log')
                [added, LogNodeObj] = containerObj.UpdateOrAddChildByAttrib(LogNodeObj, 'Name')
                LogsAdded = LogsAdded or added
                LogNodeObj.AverageTileTime = '%g' % LogData.AverageTileTime
                LogNodeObj.AverageTileDrift = '%g' % LogData.AverageTileDrift
                LogNodeObj.CaptureTime = '%g' % (LogData.MontageEnd - LogData.MontageStart)

            except:
                (etype, evalue, etraceback) = sys.exc_info()
                prettyoutput.Log("Attempt to include logs from " + filename + " failed.\n" + evalue.message)
                prettyoutput.Log(str(etraceback))

    return LogsAdded

class IDocTileData():



    def __init__(self, ImageName):
        '''Populate all known SerialEM Idoc meta-data'''
        self.Image = ImageName  # Name of the image
        self.TiltAngle = None
        self.PieceCoordinates = None
        self.StagePosition = None
        self.Intensity = None
        self.ExposureDose = None
        self.SpotSize = None
        self.Defocus = None
        self.ImageShift = None
        self.RotationAngle = None
        self.ExposureTime = None
        self.MinMaxMean = None
        self.TargetDefocus = None
        
    def __str__(self):
        return self.Image


class IDoc():
    '''Class that parses a SerialEM idoc file'''

    @property
    def NumTiles(self):
        return len(self.tiles)

    def __init__(self):
        self.DataMode = None
        self.PixelSpacing = None
        self.ImageSize = None
        self.tiles = []
        pass

    @classmethod
    def Load(cls, idocfullPath):
        assert(os.path.exists(idocfullPath))

        with open(idocfullPath, 'r') as hIDoc:
            idocText = hIDoc.read()

            obj = IDoc()

            imageStartIndicies = [m.start for m in re.finditer('\[Image', idocText)]
            NumImages = len(imageStartIndicies)

            lines = idocText.split('\n')

            TileData = None  # Set to the last image name we've read in, if None we are reading montage properties

            for iLine in range(0, len(lines)):
                line = lines[iLine]
                line = line.strip()
                line = line.strip('[]')
                parts = line.split('=')
                if(len(parts) <= 1):
                    continue

                attribute = parts[0].strip()
                # attribute = attribute.lower()



                # If we find an image tag, create a new tiledata
                if(attribute == 'Image'):
                    imageFilename = parts[1].strip()
                    TileData = IDocTileData(imageFilename)
                    obj.tiles.append(TileData)
                else:
                    value = None
                    if(len(parts) > 1):
                        values = parts[1].split()

                        vTemp = values[0].strip()
                        if vTemp[0].isdigit() or vTemp[0] == '-':


                            # Find out how many attributes we have.
                            # Try to convert to ints, then to float
                            ConvertedValues = []
                            try:
                                for v in values:
                                    convVal = int(v.strip())
                                    ConvertedValues.append(convVal)
                            except:
                                for v in values:
                                    convVal = float(v.strip())
                                    ConvertedValues.append(convVal)

                            values = ConvertedValues
                            if len(values) == 1:
                                value = values[0]
                            else:
                                value = values

                    if not value is None:
                        if TileData is None:
                            obj.__dict__[attribute] = value
                        else:
                            TileData.__dict__[attribute] = value

            return obj

        return None


class LogTileData():
    '''Data for each individual tile in a capture'''

    @property
    def totalTime(self):
        '''Total time required to capture the file, based on interval between DoNextPiece calls in the log'''
        if self.endTime is None:
            return None

        return self.endTime - self.startTime

    @property
    def dwellTime(self):
        '''Total time required to acquire the tile after the stage stopped moving'''
        if self.stageStopTime is None:
            return None

        if self.endTime is None:
            return None

        return self.endTime - self.stageStopTime

    @property
    def settleTime(self):
        '''Total time required to for the first drift measurement below threshold after the stage stopped moving'''
        if len(self.driftStamps) == 0:
            return None

        if self.endTime is None:
            return None

        return self.endTime - self.driftStamps[-1]

    @property
    def drift(self):

        if len(self.driftStamps) > 0:
            (time, drift) = self.driftStamps[-1]
            return drift

        return None

    def __str__(self):
        text = ""
        if not self.number is None:
            text = str(self.number) + ": "
        if not self.totalTime is None:
            text = text + "%.1f" % self.totalTime
        if len(self.driftStamps) > 0:
            text = text + " %.2f " % self.drift
            if not self.driftUnits is None:
                text = text + " " + self.driftUnits

        return text

    def __init__(self, startTime):
        self.startTime = startTime  # Time when DoNextPiece was logged to begin this tile
        self.endTime = None  # Time when DoNextPiece was logged to start the next tile

        self.stageStopTime = None  # Time when the stage stopped moving

        self.driftStamps = []  # Contains tuples of time after stage move completion and measured drift
        self.settleTime = None  # Time required to capture the tile after the stage stopped moving.
        self.number = None  # The tile number in the capture
        self.driftUnits = None  # nm/sec
        self.coordinates = None

class SerialEMLog():

    @property
    def TotalTime(self):
        total = self.MontageEnd - self.MontageStart
        return total

    @property
    def AverageTileTime(self):
        total = 0.0
        for t in self.tileData.values():
            total = total + t.totalTime

        return total / len(self.tileData)

    @property
    def AverageTileDrift(self):
        total = 0.0
        count = 0
        for t in self.tileData.values():
            if t.drift is None:
                continue

            count = count + 1
            total = total + t.drift

        return total / count

    def __init__(self):
        self.tileData = {}  # The time required to capture each tile
        self.Startup = None  # SerialEM program Startup time, if known
        self.Version = None  # SerialEM version, if known
        self.PropertiesVersion = None  # Timestamp of properties file, if known
        self.MontageStart = None  # timestamp when acquire began
        self.MontageEnd = None  # timestamp when acquire ended
        pass

    @classmethod
    def Load(cls, logfullPath):
        '''Parses a SerialEM log file and extracts as much information as possible:
        '''

        # These are some samples of interesting lines this function looks for
        # Last update properties file: Sep 30, 2011
        # SerialEM Version 3.1.1a,  built Nov  9 2011  14:20:16
        # Started  4/23/2012  12:17:25
        # 2912.015: Montage Start
        # 2969.640: DoNextPiece Starting capture with stage move
        # 2980.703: BlankerProc finished stage move
        # 2984.078: SaveImage Saving image at 4 4,  file Z = 0
        # 2985.547: SaveImage Processing
        # 31197.078: Montage Done processing

        # 4839.203: Autofocus Start
        # Measured defocus = -0.80 microns                  drift = 1.57 nm/sec
        # 4849.797: Autofocus Done

        # Captures in SerialEM overlap.  Once the stage is in position the exposure is done,
        # then simultaneously the stage moves while the camera is read.  Generally the stage
        # finishes movement before the image is saved, but we should not count on this behaviour

        Data = SerialEMLog()
        NextTile = None  # The tile we are currently moving the stage, focusing on, and setting up an aquisition for.
        AcquiredTile = None  # The tile which we have an image for, but has not been read from the CCD and saved to disk yet

        with open(logfullPath, 'r') as hLog:

            line = hLog.readline(512)

            lastDriftMeasure = None
            LastAutofocusStart = None
            LastValidTimestamp = None  # Used in case the log ends abruptly to populate MontageEnd value
            while len(line) > 0:
                line = line.strip()

                # print line

                # See if the entry starts with a timestamp
                entry = line
                timestamp = None

                if len(line) == 0:
                    line = hLog.readline(512)
                    continue
                
                if line[0].isdigit():
                    try:
                        (timestamp, entry) = line.split(':', 1)
                        timestamp = float(timestamp)
                    except ValueError:
                        pass
                entry = entry.strip()

                if entry.startswith('DoNextPiece'):

                    # The very first first stage move is not a capture, so don't save a tile.
                    if entry.find('capture') >= 0:
                        # We acquired the tile, prepare the next capture
                        if not NextTile is None:
                            NextTile.endTime = timestamp
                            #
                            assert (AcquiredTile is None)  # We are overwriting an unwritten tile if this assertion fails
                            AcquiredTile = NextTile
                            NextTile = None

                    NextTile = LogTileData(timestamp)

                elif entry.startswith('Autofocus Start'):
                    LastAutofocusStart = timestamp
                elif entry.startswith('Measured defocus'):
                    if not NextTile is None and not NextTile.stageStopTime is None:
                        iDrift = entry.find('drift')
                        if iDrift > -1:
                            DriftStr = entry[iDrift:]  # example: drift = 1.57 nm/sec
                            iEqual = DriftStr.find('=')
                            if iEqual > -1:
                                ValueStr = DriftStr[iEqual + 1:]  # example 1.57 nm/sec
                                ValueStr = ValueStr.strip()
                                (Value, Units) = ValueStr.split()
                                Units = Units.strip()
                                Value = Value.strip()
                                floatValue = float(Value)
                                driftTimestamp = LastAutofocusStart - NextTile.stageStopTime
                                NextTile.driftStamps.append((driftTimestamp, floatValue))
                                NextTile.driftUnits = Units
                elif entry.startswith('SaveImage Saving'):
                    assert(not AcquiredTile is None)  # We should have already recorded a capture event and populated AcquiredTile before seeing this line in the log
                    iEqual = line.find('=')
                    if iEqual > -1:
                        ValueStr = line[iEqual + 1:]  # example 1.57 nm/sec
                        ValueStr = ValueStr.strip()
                        FileNumber = int(ValueStr)
                        AcquiredTile.number = FileNumber

                        # Determine the position in the grid
                        iAt = line.find('at')
                        if iAt >= 0:
                            CoordString = line[iAt + 2:]
                            iComma = CoordString.find(',')
                            if iComma > 0:
                                CoordString = CoordString[:iComma]
                                Coords = CoordString.split()
                                X = int(Coords[0].strip())
                                Y = int(Coords[1].strip())
                                AcquiredTile.coordinates = (X, Y)


                        Data.tileData[AcquiredTile.number] = AcquiredTile
                        AcquiredTile = None

                elif entry.endswith('finished stage move'):
                    # Save the last tile
                    NextTile.stageStopTime = timestamp

                elif entry.startswith('Last update properties file'):
                    (entry, time) = line.split(':', 1)
                    time = time.strip()
                    Data.PropertiesVersion = time
                elif entry.startswith('SerialEM Version'):
                    Data.Version = entry
                elif entry.startswith('Montage Start'):
                    Data.MontageStart = timestamp
                elif entry.startswith('Montage Done'):
                    Data.MontageEnd = timestamp
                elif entry.startswith('Started'):
                    Data.Startup = entry

                line = hLog.readline(512)

                if(not timestamp is None):
                    LastValidTimestamp = timestamp

            # If we did not find a MontageEnd value use the last valid timestamp
            if Data.MontageEnd is None and not LastValidTimestamp is None:
                Data.MontageEnd = LastValidTimestamp

        return Data


if __name__ == "__main__":

    import datetime


    Data = SerialEMLog.Load(sys.argv[1])

    dtime = datetime.timedelta(seconds=(Data.MontageEnd - Data.MontageStart))

    print "%d tiles" % len(Data.tileData)
    print "Average drift: %g nm/sec" % Data.AverageTileDrift
    print "Average tile time: %g sec" % Data.AverageTileTime
    print "Total time: %s" % str(dtime)

    lines = []
    maxdrift = None
    NumTiles = int(0)
    fastestTime = None
    colors = ['black', 'blue', 'green', 'yellow', 'orange', 'red', 'purple']

    DriftGrid = []
    c = []
    for t in Data.tileData.values():
        if not (t.dwellTime is None or t.drift is None):
            time = []
            drift = []

            for s in t.driftStamps:
                time.append(s[0])
                drift.append(s[1])

            colorVal = 'black'
            numPoints = len(t.driftStamps)
            if  numPoints < len(colors):
                colorVal = colors[numPoints]

            c.append(colorVal)

            DriftGrid.append((t.coordinates[0], t.coordinates[1], pow(t.dwellTime, 2)))
            maxdrift = max(maxdrift, t.driftStamps[-1][1])
            if fastestTime is None:
                fastestTime = t.totalTime
            else:
                fastestTime = min(fastestTime, t.totalTime)

            lines.append((time, drift))
            NumTiles = NumTiles + 1

    print "Fastest Capture: %g" % fastestTime
    print "Total tiles: %d" % NumTiles

   # PlotHistogram.PolyLinePlot(lines, Title="Stage settle time, max drift %g" % maxdrift, XAxisLabel='Dwell time (sec)', YAxisLabel="Drift (nm/sec)", OutputFilename=None)

    x = []
    y = []
    s = []
    for d in DriftGrid:
        x.append(d[0])
        y.append(d[1])
        s.append(d[2])

    PlotHistogram.ScatterPlot(x, y, s, c=c, Title="Drift recorded at each capture position in mosaic\nradius = dwell time ^ 2, color = # of tries")


