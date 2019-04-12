'''

Imports .idoc files generated by `SerialEM`_.  The importer expects the input
path to be a folder containing a separate subfolder for each section.  Section
subfolders should be named with the section number.  An optional 
underscore may follow the section number with a friendly name for the section.

Section subfolders should contain the .idoc file, any images associated with the 
.idoc, an optional notes.txt file, and the .log generated during capture by SerialEM. 

Example:

* BobcatSeriesForBob

  * 0001_EggID4567

    * capture.idoc
    * capture.log
    * notes.txt
    * 001.tif
    * 002.tif
    * ...
    * 1245.tif

  * 0002_EggID7645

    * ... 

.. _SerialEM: http://bio3d.colorado.edu/SerialEM/

'''

import re
import nornir_buildmanager.templates
from nornir_buildmanager.VolumeManagerETree import *
from nornir_buildmanager.operations.tile import VerifyTiles
import nornir_buildmanager.importers
from nornir_imageregistration.files import mosaicfile
from nornir_imageregistration.mosaic import Mosaic
from nornir_imageregistration import image_stats
from nornir_shared.images import *
import nornir_shared.files as files
from nornir_shared.histogram import *
from nornir_shared.mathhelper import ListMedian
from nornir_shared.files import RemoveOutdatedFile
import nornir_shared.plot as plot
import logging
import collections
import nornir_pools
import numpy
import nornir_buildmanager.importers.serialemlog as serialemlog


def Import(VolumeElement, ImportPath, extension=None, *args, **kwargs):
    '''Import the specified directory into the volume'''

    if extension is None:
        extension = 'idoc'
        
    # TODO, set the defaults at the volume level in the meta-data and pull from there
    
    MinCutoff = float(kwargs.get('Min'))
    MaxCutoff = float(kwargs.get('Max'))
    ContrastCutoffs = (MinCutoff, MaxCutoff)
    CameraBpp = kwargs.get('CameraBpp',None)
        
    if MinCutoff < 0.0 or MinCutoff > 1.0:
        raise ValueError("Min must be between 0 and 1: %f" % MinCutoff)
    
    if MaxCutoff < 0.0 or MaxCutoff > 1.0:
        raise ValueError("Max must be between 0 and 1: %f" % MaxCutoff)
    
    if MinCutoff >= MaxCutoff:
        raise ValueError("Max must be greater than Min: %f is not less than %f" % (MinCutoff, MaxCutoff))
    
    FlipList = nornir_buildmanager.importers.GetFlipList(ImportPath)
    histogramFilename = os.path.join(ImportPath, nornir_buildmanager.importers.DefaultHistogramFilename)
    ContrastMap = nornir_buildmanager.importers.LoadHistogramCutoffs(histogramFilename)
    if len(ContrastMap) == 0:
        nornir_buildmanager.importers.CreateDefaultHistogramCutoffFile(histogramFilename)

    if not os.path.exists(ImportPath):
        raise ValueError("Import Path does not exist: %s" % ImportPath) 

    DirList = files.RecurseSubdirectoriesGenerator(ImportPath, RequiredFiles="*." + extension, ExcludeNames=[], ExcludedDownsampleLevels=[])

    DataFound = False 

    for path in DirList:
        for idocFullPath in glob.glob(os.path.join(path, '*.idoc')):
            DataFound = True
            yield SerialEMIDocImport.ToMosaic(VolumeElement, idocFullPath, ContrastCutoffs, VolumeElement.FullPath, FlipList=FlipList, CameraBpp=CameraBpp, ContrastMap=ContrastMap)

    if not DataFound:
        raise ValueError("No data found in ImportPath %s" % ImportPath)

              


class SerialEMIDocImport(object):
    
    

    @classmethod
    def ToMosaic(cls, VolumeObj, idocFileFullPath, ContrastCutoffs, OutputPath=None, Extension=None, OutputImageExt=None, TargetBpp=None, FlipList=None, ContrastMap=None, CameraBpp=None, debug=None):
        '''
        This function will convert an idoc file in the given path to a .mosaic file.
        It will also rename image files to the requested extension and subdirectory.
        TargetBpp is calculated based on the number of bits required to encode the values
        between the median min and max values
        :param list FlipList: List of section numbers which should have images flipped
        :param dict ContrastMap: Dictionary mapping section number to (Min, Max, Gamma) tuples 
        '''
        if(OutputImageExt is None):
            OutputImageExt = 'png'

        if(Extension is None):
            Extension = 'idoc'
            
        if TargetBpp is None:
            TargetBpp = 8
            
        if FlipList is None:
            FlipList = []
            
        if ContrastMap is None:
            ContrastMap = {}
            
        SaveChannel = False
        
        idocFilePath = cls.GetIDocPathWithoutSpaces(idocFileFullPath)

        # Default to the directory above ours if an output path is not specified
        if OutputPath is None:
            OutputPath = os.path.join(idocFilePath, "..")

        os.makedirs(OutputPath, exist_ok=True)

        logger = logging.getLogger(__name__ + '.' + str(cls.__name__) + "ToMosaic")

        # Report the current stage to the user
        prettyoutput.CurseString('Stage', "SerialEM to Mosaic " + str(idocFileFullPath))

        SectionNumber = 0
        (ParentDir, sectionDir) = cls.GetDirectories(idocFileFullPath)
          
        BlockObj = BlockNode.Create('TEM')
        [saveBlock, BlockObj] = VolumeObj.UpdateOrAddChild(BlockObj)
         
        # If the parent directory doesn't have the section number in the name, change it
        ExistingSectionInfo = cls.GetSectionInfo(sectionDir)
        if(ExistingSectionInfo[0] < 0):
            i = 5
#            SectionNumber = SectionNumber + 1
#            newPathName = ('%' + nornir_buildmanager.templates.Current.SectionFormat) % SectionNumber + '_' + sectionDir
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

        # Check for underscores.  If there is an underscore and the first part is the sectionNumber, then use everything after as the section name
        SectionName = ('%' + nornir_buildmanager.templates.Current.SectionFormat) % SectionNumber
        SectionPath = ('%' + nornir_buildmanager.templates.Current.SectionFormat) % SectionNumber
        try:
            parts = sectionDir.partition("_")
            if not parts is None:
                if len(parts[2]) > 0:
                    SectionName = parts[2]
        except:
            pass

        sectionObj = SectionNode.Create(SectionNumber,
                                              SectionName,
                                              SectionPath)

        [saveSection, sectionObj] = BlockObj.UpdateOrAddChildByAttrib(sectionObj, 'Number')
        sectionObj.Name = SectionName

        # Create a channel group 
        [saveChannel, channelObj] = sectionObj.UpdateOrAddChildByAttrib(ChannelNode.Create('TEM'), 'Name')
  
        ChannelPath = channelObj.FullPath
        OutputSectionPath = os.path.join(OutputPath, ChannelPath)
        # Create a channel group for the section

        # I started ignoring existing supertile.mosaic files so I could rebuild sections where
        # a handful of tiles were corrupt
        # if(os.path.exists(SupertilePath)):
        #    continue

        Flip = SectionNumber in FlipList;
        if(Flip):
            prettyoutput.Log("Found in FlipList.txt, flopping images")

        IDocData = IDoc.Load(idocFilePath, CameraBpp=CameraBpp)

        assert(hasattr(IDocData, 'PixelSpacing'))
        assert(hasattr(IDocData, 'DataMode'))
        assert(hasattr(IDocData, 'ImageSize'))

        # If there are no tiles... return
        if IDocData.NumTiles == 0:
            prettyoutput.Log("No tiles found in IDoc: " + idocFilePath)
            return

        # See if we can find a notes file...
        TryAddNotes(channelObj, sectionDir, logger)
        TryAddLogs(channelObj, sectionDir, logger)

        AddIdocNode(channelObj, idocFilePath, IDocData, logger)

        # Set the scale
        [added, ScaleObj] = cls.CreateScaleNode(IDocData, channelObj)
        
        # Parse the images
        ImageBpp = IDocData.GetImageBpp()            
        if ImageBpp is None:
            ImageBpp = cls.GetImageBpp(IDocData, sectionDir) 

        FilterName = 'Raw' + str(TargetBpp)
        if(TargetBpp is None):
            FilterName = 'Raw'

        histogramFullPath = os.path.join(sectionDir, 'Histogram.xml')
        
        IDocData.RemoveMissingTiles(sectionDir)
        source_tile_list = [os.path.join(sectionDir, t.Image) for t in IDocData.tiles ]
          
        (ActualMosaicMin, ActualMosaicMax, Gamma) = cls.GetSectionContrastSettings(SectionNumber, ContrastMap, ContrastCutoffs, source_tile_list, IDocData, histogramFullPath)
        ActualMosaicMax = numpy.around(ActualMosaicMax)
        ActualMosaicMin = numpy.around(ActualMosaicMin)
        
        contrast_mismatch = channelObj.RemoveFilterOnContrastMismatch(FilterName, ActualMosaicMin, ActualMosaicMax, Gamma)
    
        Pool = nornir_pools.GetGlobalThreadPool()
        #_PlotHistogram(histogramFullPath, SectionNumber, ActualMosaicMin, ActualMosaicMax)
        Pool.add_task(histogramFullPath, _PlotHistogram, histogramFullPath, SectionNumber, ActualMosaicMin, ActualMosaicMax, force_recreate=contrast_mismatch)
        
        
        ImageConversionRequired = contrast_mismatch

        # Create a channel for the Raw data 
        [added_filter, filterObj] = channelObj.UpdateOrAddChildByAttrib(FilterNode.Create(Name=FilterName), 'Name')
        if added_filter:
            ImageConversionRequired = True

        filterObj.SetContrastValues(ActualMosaicMin, ActualMosaicMax, Gamma)
        filterObj.BitsPerPixel = TargetBpp

        SupertileName = 'Stage'
        SupertileTransform = SupertileName + '.mosaic'
        SupertilePath = os.path.join(OutputSectionPath, SupertileTransform)

        # Check to make sure our supertile mosaic file is valid
        RemoveOutdatedFile(idocFilePath, SupertilePath)

        [added_transform, transformObj] = channelObj.UpdateOrAddChildByAttrib(TransformNode.Create(Name=SupertileName,
                                                                         Path=SupertileTransform,
                                                                         Type='Stage'),
                                                                         'Path')

        [added_tilepyramid, PyramidNodeObj] = filterObj.UpdateOrAddChildByAttrib(TilePyramidNode.Create(Type='stage',
                                                                            NumberOfTiles=IDocData.NumTiles),
                                                                            'Path')

        [added_level, LevelObj] = PyramidNodeObj.GetOrCreateLevel(1, GenerateData=False)

        Tileset = NornirTileset.CreateTilesFromIDocTileData(IDocData.tiles, InputTileDir=sectionDir, OutputTileDir=LevelObj.FullPath, OutputImageExt=OutputImageExt)

        

        # Make sure the target LevelObj is verified        
        if not os.path.exists(LevelObj.FullPath):
            os.makedirs(LevelObj.FullPath, exist_ok=True)
        else:
            Tileset.RemoveStaleTilesFromOutputDir(SupertilePath=SupertilePath)
            VerifyTiles(filterObj.TilePyramid.GetLevel(1))

        SourceToMissingTargetMap = Tileset.GetSourceToMissingTargetMap()

        # Figure out if we have to move or convert images
        if len(SourceToMissingTargetMap) == 0:
            ImageConversionRequired = False
        else:
            ImageConversionRequired = (not ImageBpp == TargetBpp) or (ImageConversionRequired or Tileset.ImageConversionRequired)

        if(ImageConversionRequired):
            Invert = False 
            filterObj.SetContrastValues(ActualMosaicMin, ActualMosaicMax, Gamma)
            filterObj.TilePyramid.NumberOfTiles = IDocData.NumTiles
            # andValue = cls.GetBitmask(ActualMosaicMin, ActualMosaicMax, TargetBpp)
            #nornir_shared.images.ConvertImagesInDict(SourceToMissingTargetMap, Flip=Flip, Bpp=TargetBpp, Invert=Invert, bDeleteOriginal=False, MinMax=[ActualMosaicMin, ActualMosaicMax])
            nornir_imageregistration.ConvertImagesInDict(SourceToMissingTargetMap, Flip=Flip, Bpp=ImageBpp, OutputBpp=TargetBpp, Invert=Invert, bDeleteOriginal=False, MinMax=[ActualMosaicMin, ActualMosaicMax], Gamma=Gamma)

        elif(Tileset.ImageMoveRequired):
            for f in SourceToMissingTargetMap:
                shutil.copy(f, SourceToMissingTargetMap[f])

        # If we wrote new images replace the .mosaic file
        if len(SourceToMissingTargetMap) > 0 or not os.path.exists(SupertilePath):
            # Writing this file indicates import succeeded and we don't need to repeat these steps, writing it will possibly invalidate a lot of downstream data
            # We need to flip the images.  This may be a Utah scope issue, our Y coordinates are inverted relative to the images.  To fix this
            # we flop instead of flip and reverse when writing the coordinates
            mosaicfile.MosaicFile.Write(SupertilePath, Entries=Tileset.GetPositionsForTargets(), Flip=not Flip, ImageSize=IDocData.ImageSize, Downsample=1);
            MFile = mosaicfile.MosaicFile.Load(SupertilePath)

            # Sometimes files fail to convert, when this occurs remove them from the .mosaic
            if MFile.RemoveInvalidMosaicImages(LevelObj.FullPath):
                MFile.Save(SupertilePath)
 
            Mosaic.TranslateMosaicFileToZeroOrigin(SupertilePath)
            transformObj.ResetChecksum()
            SaveChannel = True
            # transformObj.Checksum = MFile.Checksum

        if saveBlock:
            return VolumeObj
        elif saveSection:
            return BlockObj
        elif saveChannel:
            return sectionObj
        elif  added_transform or added_tilepyramid or added_level or ImageConversionRequired or SaveChannel or contrast_mismatch:
            return channelObj
        return None

    @classmethod
    def GetSectionContrastSettings(cls, SectionNumber, ContrastMap, ContrastCutoffs, SourceImagesFullPaths, idoc_data, histogramFullPath):
        '''Clear and recreate the filters tile pyramid node if the filters contrast node does not match'''
        Gamma = 1.0
        
        #We don't have to run this step, but it ensures the histogram is up to date
        (ActualMosaicMin, ActualMosaicMax) = _GetMinMaxCutoffs(SourceImagesFullPaths, ContrastCutoffs[0], 1.0 - ContrastCutoffs[1], idoc_data, histogramFullPath)
        
        if SectionNumber in ContrastMap:
            ActualMosaicMin = ContrastMap[SectionNumber].Min
            ActualMosaicMax = ContrastMap[SectionNumber].Max
            Gamma = ContrastMap[SectionNumber].Gamma
        
        return (ActualMosaicMin, ActualMosaicMax, Gamma)

    @classmethod
    def GetImageBpp(cls, IDocData, sectionDir):
        ImageBpp = IDocData.GetImageBpp()
        if ImageBpp is None:
            # Figure out the bit depth of the input
            tile = IDocData.tiles[0] 
            SourceImageFullPath = os.path.join(sectionDir, tile.Image)
            ImageBpp = GetImageBpp(SourceImageFullPath)
        if(not ImageBpp is None):
            prettyoutput.Log("Source images are " + str(ImageBpp) + " bits per pixel")
        else:
            prettyoutput.Log("Could not determine source image BPP")
            raise ValueError("Could not determine source image BPP")

        return ImageBpp

    @classmethod
    def CreateScaleNode(cls, IDocData, channelObj):
        '''Create a scale node for the channel
        :return: ScaleNode object that was created'''
        scaleValueInNm = float(IDocData.PixelSpacing) / 10.0
        return channelObj.SetScale(scaleValueInNm)

    @classmethod
    def GetBitmask(cls, ImageMin, ImageMax, TargetBpp):
        '''
        :param int ImageMin: Minimum value
        :param int ImageMax: Maximum value
        :param int TargetBpp: Desired bits-per-pixel after applying the bitmask,i.e. length of the bitmask
        :return: A bitmask which removes bits which do not contain information for integer values between min and max.'''

        # Figure out how many bits are required to encode the values between min and max
        ValueRange = ImageMax - ImageMin

        if(TargetBpp > 8):
            TargetBpp = int(math.ceil(math.log(ValueRange, 2)))

        # Figure out the left shift required to erase the top bits
        MaxUsefulHighBit = int(math.ceil(math.log(ImageMax, 2)))  # Floor because bits are numbered 0-N
        MinUsefulLowBit = (MaxUsefulHighBit - TargetBpp)

        if MinUsefulLowBit < 0:
            MinUsefulLowBit = 0

        # Build a value to AND with
        andValue = 0
        for i in range(MinUsefulLowBit, MaxUsefulHighBit):
            andValue = andValue + pow(2, i)
            
        return andValue

    
def _GetMinMaxCutoffs(listfilenames, MinCutoff, MaxCutoff, idoc_data, histogramFullPath=None):
    
    histogramObj = None
    if not histogramFullPath is None:
        if os.path.exists(histogramFullPath):
            histogramObj = Histogram.Load(histogramFullPath)

    if histogramObj is None:
        prettyoutput.Log("Collecting mosaic min/max data")
        
        Bpp = idoc_data.GetImageBpp()
        if Bpp is None:
            Bpp = nornir_shared.images.GetImageBpp(listfilenames[0])
        
        numBins = 256
        if Bpp >= 11:
            numBins = 2048
            
        maxVal = idoc_data.Max
        if idoc_data.CameraBpp is not None:
            if (1 << idoc_data.CameraBpp) - 1 < maxVal:
                maxVal = (1 << idoc_data.CameraBpp) - 1
            
        histogramObj = image_stats.Histogram(listfilenames, Bpp=Bpp, MinVal=idoc_data.Min, MaxVal=idoc_data.Max, numBins=numBins)

        if not histogramFullPath is None:
            histogramObj = _CleanOutliersFromIDocHistogram(histogramObj)
            histogramObj.Save(histogramFullPath)

    assert(not histogramObj is None)

    # I am willing to clip 1 pixel every hundred thousand on the dark side, and one every ten thousand on the light
    return histogramObj.AutoLevel(MinCutoff, MaxCutoff)


def _CleanOutliersFromIDocHistogram(hObj):
    '''
    For Max-Value outliers this is a legacy function that supports old versions of SerialEM that falsely reported
    maxint for some pixels even though the camera was a 14-bit camera.  This applies to the original RC1 data. 
    By the time RC2 was collected in March 2018 this bug was fixed
    
    However this function is worth retaining because Max and Min outliers can rarely occur if a tile is removed 
    from the input before import but remain in the iDoc data.  
    '''
    
    hNew = nornir_shared.histogram.Histogram.TryRemoveMaxValueOutlier(hObj, TrimOnly=False)
    if hNew is not None:
        hObj = hNew
        
    hNew = nornir_shared.histogram.Histogram.TryRemoveMinValueOutlier(hObj, TrimOnly=False)
    if hNew is not None:
        hObj = hNew
    
    return hObj
    
def _PlotHistogram(histogramFullPath, sectionNumber, minCutoff, maxCutoff, force_recreate):    
    HistogramImageFullPath = os.path.join(os.path.dirname(histogramFullPath), 'Histogram.png')
    ImageRemoved = RemoveOutdatedFile(histogramFullPath, HistogramImageFullPath)
    if ImageRemoved or force_recreate or not os.path.exists(HistogramImageFullPath):
#        pool = nornir_pools.GetGlobalMultithreadingPool()
        # pool.add_task(HistogramImageFullPath, plot.Histogram, histogramFullPath, HistogramImageFullPath, Title="Section %d Raw Data Pixel Intensity" % (sectionNumber), LinePosList=[minCutoff, maxCutoff])
        plot.Histogram(histogramFullPath, HistogramImageFullPath, Title="Section %d Raw Data Pixel Intensity" % (sectionNumber), LinePosList=[minCutoff, maxCutoff])


class NornirTileset():
    
    Tile = collections.namedtuple("NornirTile", ('SourceImageFullPath', 'TargetImageFullPath', 'Position'))
    
    @property
    def MissingInputImages(self):
        return self._MissingInputImages
    
    @MissingInputImages.setter
    def MissingInputImages(self, value):
        self._MissingInputImages = value
    
    @property
    def ImageMoveRequired(self):
        if self._ImageMoveRequired is None:
            self._ImageMoveRequired = self._IsImageMoveRequired()
        return self._ImageMoveRequired
    
    def _IsImageMoveRequired(self):
        for t in self._tiles:
            if t.SourceImageFullPath != t.TargetImageFullPath:
                return True
            
        return False
    
    @property
    def ImageConversionRequired(self):
        if self._ImageConversionRequired is None:
            self._ImageConversionRequired = self._IsImageConversionRequired()
            
        return self._ImageConversionRequired
    
    def _IsImageConversionRequired(self):
        '''True if the extensions do not match'''
        for t in self._tiles:
            [_, SourceImageExt] = os.path.splitext(t.SourceImageFullPath)
            [_, TargetImageExt] = os.path.splitext(t.TargetImageFullPath) 
            if SourceImageExt.lower() != TargetImageExt.lower():
                return True
    
    def AddTile(self, tile):
        self._tiles.append(tile)
        self._ImageMoveRequired = None
        self._ImageConversionRequired = None
    
    @property
    def SourceImagesFullPaths(self):
        imagePaths = []
        for t in self._tiles:
            imagePaths.append(t.SourceImageFullPath)
            
        return imagePaths
          
    @property 
    def Tiles(self):
        return self._tiles
    
    def GetSourceToMissingTargetMap(self):
        ''':return: A dictionary mapping source image paths to missing target image paths'''
        
        SourceToTargetMap = {}
        for t in self._tiles:
            if os.path.exists(t.SourceImageFullPath) and not os.path.exists(t.TargetImageFullPath):
                SourceToTargetMap[t.SourceImageFullPath] = t.TargetImageFullPath
                
        return SourceToTargetMap
                
    def RemoveStaleTilesFromOutputDir(self, SupertilePath):
        for t in self._tiles:
            if os.path.exists(t.SourceImageFullPath):
                RemoveOutdatedFile(t.SourceImageFullPath, SupertilePath)
                RemoveOutdatedFile(t.SourceImageFullPath, t.TargetImageFullPath)
    
    def GetPositionsForTargets(self):
        positionMap = {}
        for t in self._tiles:
            if os.path.exists(t.TargetImageFullPath):
                positionMap[t.TargetImageFullPath] = t.Position
            
        return positionMap
        
    def __init__(self, OutputImageExt):
        self._tiles = []
        self._MissingInputImages = False  # True if some of the IDocImages are missing from the disk
        self._ImageMoveRequired = False  # True if there are images that can be moved
        self._ImageConversionRequired = False  # True if there are images that need to be converted
        self._OutputImageExt = OutputImageExt
        
    @classmethod
    def CreateTilesFromIDocTileData(cls, tiles, InputTileDir, OutputTileDir, OutputImageExt):
        ''' 
        :param tiles IDocTileData: List of tiles to build dictionaries from
        '''
        
        # SerialEM begins numbering file names from zero.  So we will too. 
        ImageNumber = -1
        
        obj = NornirTileset(OutputImageExt)
        
        for tile in tiles:

            [ImageRoot, ImageExt] = os.path.splitext(tile.Image)

            ImageExt = ImageExt.strip('.')
            ImageExt = ImageExt.lower()
            ImageNumber = ImageNumber + 1

            SourceImageFullPath = os.path.join(InputTileDir, tile.Image)
            if not os.path.exists(SourceImageFullPath):
                prettyoutput.Log("Could not locate import image: " + SourceImageFullPath)
                obj.MissingInputImage = True
                continue
            
            # I rename the converted image because I haven't checked how robust viking is with non-numbered images.  I'm 99% sure it can handle it, but I don't want to test now.
            ConvertedImageName = (nornir_buildmanager.templates.Current.TileCoordFormat % ImageNumber) + '.' + OutputImageExt
            TargetImageFullPath = os.path.join(OutputTileDir, ConvertedImageName)
            
            obj.AddTile(NornirTileset.Tile(SourceImageFullPath, TargetImageFullPath, Position=tile.PieceCoordinates[0:2]))
        
        return obj


def AddIdocNode(containerObj, idocFullPath, idocObj, logger):

    # Copy the idoc file to the output directory
    idocPath = os.path.basename(idocFullPath)
    IDocNodeObj = DataNode.Create(Path=idocPath, attrib={'Name' : 'IDoc'})
    containerObj.RemoveOldChildrenByAttrib('Data', 'Name', 'IDoc')
    [added, IDocNodeObj] = containerObj.UpdateOrAddChildByAttrib(IDocNodeObj, 'Name')

    CopiedFileFullPath = os.path.join(containerObj.FullPath, idocPath)
    if not os.path.exists(CopiedFileFullPath):
        os.makedirs(containerObj.FullPath, exist_ok=True)
        
        shutil.copyfile(idocFullPath, CopiedFileFullPath)

    # Copy over attributes from the idoc
    for k in list(idocObj.__dict__.keys()):
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

    for k in list(tile.__dict__.keys()):
        v = tile.__dict__[k]

        if k[0] == '_':
            continue

        if isinstance(v, list):
            continue

        if k == 'Defocus':
            continue

        setattr(IDocNodeObj, k, v)

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
                    os.makedirs(containerObj.FullPath, exist_ok=True)
                    shutil.copyfile(filename, CopiedNotesFullPath)
                    NotesAdded = True

                with open(filename, 'r') as f:
                    notesTxt = f.read()
                    (base, ext) = os.path.splitext(filename)
                    encoding = "utf-8"
                    ext = ext.lower()
                    # notesTxt = notesTxt.encode(encoding)

                    notesTxt = notesTxt.replace('\0', '')

                    if len(notesTxt) > 0:
                        # XMLnotesTxt = notesTxt
                        # notesTxt = notesTxt.encode('utf-8')
                        XMLnotesTxt = escape(notesTxt)

                        # Create a Notes node to save the notes into
                        NotesNodeObj = NotesNode.Create(Text=XMLnotesTxt, SourceFilename=NotesFilename)
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
                os.makedirs(containerObj.FullPath, exist_ok=True)
                
                shutil.copyfile(filename, CopiedLogsFullPath)
                LogsAdded = True

            # OK, try to parse the logs
            try:
                LogData = serialemlog.SerialEMLog.Load(filename)
                if LogData is None:
                    pass

                # Create a Notes node to save the logs into
                LogNodeObj = DataNode.Create(Path=NotesFilename, attrib={'Name':'Log'})
                containerObj.RemoveOldChildrenByAttrib('Data', 'Name', 'Log')
                [added, LogNodeObj] = containerObj.UpdateOrAddChildByAttrib(LogNodeObj, 'Name')
                LogsAdded = LogsAdded or added
                LogNodeObj.AverageTileTime = '%g' % LogData.AverageTileTime
                LogNodeObj.AverageTileDrift = '%g' % LogData.AverageTileDrift
                LogNodeObj.CaptureTime = '%g' % (LogData.MontageEnd - LogData.MontageStart)

            except:
                (etype, evalue, etraceback) = sys.exc_info()
                prettyoutput.Log("Attempt to include logs from " + filename + " failed.\n" + str(evalue))
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
        self._MinMaxMean = None
        self.TargetDefocus = None
        
        self._Min = None
        self._Max = None
        self._Mean = None

    def __str__(self):
        return self.Image
    
    @property
    def Min(self):
        return self._Min
    
    @property
    def Max(self):
        return self._Max
    
    @Max.setter
    def Max(self, val):
        self._Max = val
    
    @property
    def Mean(self):
        return self._Mean
    
    @property
    def MinMaxMean(self):
        return self._MinMaxMean
    
    @MinMaxMean.setter
    def MinMaxMean(self, val):
        '''Expects to be set to a three part list with integer or float values'''
        self._MinMaxMean = val
        
        self._Min = val[0]
        self._Max = val[1]
        self._Mean = val[2]
         

class IDoc():
    '''Class that parses a SerialEM idoc file'''

    @property
    def NumTiles(self):
        return len(self.tiles)
    
    @property
    def CameraBpp(self):
        return self._CameraBpp

    def __init__(self):
        self.DataMode = None
        self.PixelSpacing = None
        self.ImageSize = None
        self.tiles = []
        self._CameraBpp = None
        pass
            
    def _SetCameraBpp(self, bpp):
        '''Ensure the maximum intensity reported for tiles does not exceed the known capability of the camera'''
        self._CameraBpp = bpp
        
        if self._CameraBpp is not None:
            maxPossible = 1 << bpp
            for t in self.tiles:
                if t.Max > maxPossible:
                    t.Max = maxPossible

    
    def RemoveMissingTiles(self, path):
        existingTiles = []
        for t in self.tiles: 
            tFullPath = os.path.join(path, t.Image)
            if os.path.exists(tFullPath):
                existingTiles.append(t)
                
        self.tiles = existingTiles

    def GetImageBpp(self):
        ''':return: Bits per pixel if specified in the IDoc, otherwise None'''
        ImageBpp = None
        
        
        if (hasattr(self, 'DataMode')):
            if self.DataMode == 0:
                ImageBpp = 8
            elif self.DataMode == 1:
                ImageBpp = 16
            elif self.DataMode == 6:
                ImageBpp = 16
        else:
            if not self.Max is None:
                ImageBpp = math.ceil(math.log2(self.Max)) 

        return ImageBpp
    
    @property
    def Max(self):
        '''
        For Max-Value outliers old versions of SerialEM falsely reported
        maxint for some pixels even though the camera was a 14-bit camera.  This applies to the original RC1 data. 
        By the time RC2 was collected in March 2012 this bug was fixed
            :return: Max pixel value across all tiles
        '''
        
        return max([t.Max for t in self.tiles])
    
    @property
    def Min(self):
        ''':return: Max pixel value across all tiles'''
        return min([t.Min for t in self.tiles])
    
    @property
    def Mean(self):
        ''':return: Max pixel value across all tiles'''
        return numpy.mean([t.Mean for t in self.tiles])

    @classmethod
    def Load(cls, idocfullPath, CameraBpp=None):
        '''
        :param int CameraBpp: Forces the maximum value of tiles to not exceed the known bits-per-pixel capability of the camera, ignored if None
        '''
        assert(os.path.exists(idocfullPath))

        with open(idocfullPath, 'r') as hIDoc:
            idocText = hIDoc.read()

            idocObj = IDoc()

            #imageStartIndicies = [m.start for m in re.finditer('\[Image', idocText)]
            #NumImages = len(imageStartIndicies)

            lines = idocText.split('\n')

            tileObj = None  # Set to the last image name we've read in, if None we are reading montage properties

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
                    tileObj = IDocTileData(imageFilename)
                    idocObj.tiles.append(tileObj)
                else:
                    value = None
                    if(len(parts) > 1):
                        values = parts[1].split()

                        vTemp = values[0].strip()
                        if vTemp[0].isdigit() or vTemp[0] == '-':

                            # Find out how many attributes we have.
                            # Try to convert to ints, then to float
                            ConvertedValues = []
                            for v in values:
                                v = v.strip()
                                convVal = None
                                
                                try:
                                    convVal = int(v)
                                except ValueError:
                                    try:
                                        convVal = float(v)
                                    except:
                                        convVal = v
                                        pass
                                    pass
                                                                    
                                ConvertedValues.append(convVal)
                                
                            values = ConvertedValues
                            if len(values) == 1:
                                value = values[0]
                            else:
                                value = values

                    if not value is None:
                        if tileObj is None:
                            setattr(idocObj, attribute, value)
                            #idocObj.__dict__[attribute] = value
                        else:
                            setattr(tileObj, attribute, value) 
                            
            idocObj._SetCameraBpp(CameraBpp)
            return idocObj

        return None


