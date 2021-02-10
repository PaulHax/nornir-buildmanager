'''

Imports .pmg files generated by `Surveyor`_.  The importer expects the input
path to be a folder containing a separate subfolder for each section.  Section
subfolders follow this naming convention:

Slide#_Block#_Initials_Mag_Spot_Probe

The last two components of the name, Spot and Probe, are used as section number and channel name respectively.
The other components are appended to the directory name

Section subfolders contain the .pmg file and any images associated with the 
.pmg. 

Example:

* Slide1234_Block5432_Bobcat

  * 1234_5432_JRA_40X_01_Glutamate

    * capture.pmg
    * 001.tif
    * 002.tif
    * ...
    * 1245.tif

  * 0002_EggID7645

    * ... 

.. _Surveyor: http://www.objectiveimaging.com/

'''

import glob
import logging
import os
import shutil
import sys

from nornir_buildmanager import templates
import nornir_buildmanager
from nornir_buildmanager.VolumeManagerETree import *
from nornir_buildmanager.importers import filenameparser, GetFlipList
from nornir_buildmanager.operations.tile import VerifyTiles
import nornir_imageregistration
from nornir_imageregistration import image_stats
from nornir_imageregistration.files import mosaicfile
import nornir_shared.files
from nornir_shared.images import *

from .filenameparser import ParseFilename, mapping
import nornir_shared.prettyoutput as prettyoutput


def Import(VolumeElement, ImportPath, scaleValueInNm, extension=None, *args, **kwargs):
    '''Import the specified directory into the volume'''

    if extension is None:
        extension = 'idoc'


    DirList = nornir_shared.files.RecurseSubdirectoriesGenerator(ImportPath, RequiredFiles="*." + extension, ExcludeNames=[], ExcludedDownsampleLevels=[])
    for path in DirList:
        for idocFullPath in glob.glob(os.path.join(path, '*.' + extension)):
            PMGImport.ToMosaic(VolumeElement, idocFullPath, scaleValueInNm, VolumeElement.FullPath, *args, **kwargs)

    return VolumeElement


DEBUG = False

'''#PMG Files are expected to have this naming convention:
       # Slide#_Block#_Initials_Mag_Spot_Probe
       # Only the last two, Spot and Probe, are used as section #
       # and channel name respectively.  The others are appended
       # to the directory name'''
pmgMappings = [ mapping('Slide', typefunc=int),
               mapping('Block', typefunc=str),
               mapping('Section', typefunc=int, default=None),
               mapping('Initials', typefunc=str),
               mapping('Mag', typefunc=str),
               mapping('Spot', typefunc=int),
               mapping('Probe', typefunc=str)]

def ParsePMGFilename(PMGPath):

    return filenameparser.ParseFilename(PMGPath, pmgMappings)


class PMGInfo(filenameparser.FilenameInfo):

    def __init__(self, **kwargs):
        self.Slide = None
        self.Block = None
        self.Initials = None
        self.Mag = None
        self.Spot = None
        self.Probe = None
        self.Section = None
        self.NumberOfImages = None

        super(PMGInfo, self).__init__(**kwargs)

class PMGImport(object):

    @classmethod
    def ToMosaic(cls, VolumeObj, PMGFullPath, scaleValueInNm, OutputPath=None, Extension=None, OutputImageExt=None, TileOverlap=None, TargetBpp=None, debug=None, *args, **kwargs):

        '''#Converts a PMG
        #PMG files are created by Objective Imaging's Surveyor. 
        #This function expects a directory to contain a single PMG file with the tile images in the same directory
        #Returns the SectionNumber and ChannelName of PMG processed.  Otherwise [None,None]'''

        ParentDir = os.path.dirname(PMGFullPath)
        sectionDir = os.path.basename(PMGFullPath)
        
        #Ensure scale is in a format we understand
        scaleValueInNm = float(scaleValueInNm)

        # Default to the directory above ours if an output path is not specified
        if OutputPath is None:
            OutputPath = os.path.join(PMGFullPath, "..")

        # If the user did not supply a value, use a default
        if(TileOverlap is None):
            TileOverlap = 0.10

        if (TargetBpp is None):
            TargetBpp = 8

        # Report the current stage to the user
        # prettyoutput.CurseString('Stage', "PMGToMosaic " + InputPath)

        BlockName = 'TEM'
        BlockObj = BlockNode.Create('TEM')
        [addedBlock, BlockObj] = VolumeObj.UpdateOrAddChild(BlockObj)

        ChannelName = None
         # TODO wrap in try except and print nice error on badly named files?
        PMG = ParseFilename(PMGFullPath, pmgMappings)
        PMGDir = os.path.dirname(PMGFullPath)

        if(PMG is None):
            raise Exception("Could not parse section from PMG filename: %s" + PMGFullPath)

        if PMG.Section is None:
            PMG.Section = PMG.Spot

        sectionObj = SectionNode.Create(PMG.Section)

        [addedSection, sectionObj] = BlockObj.UpdateOrAddChildByAttrib(sectionObj, 'Number')

        # Calculate our output directory.  The scripts expect directories to have section numbers, so use that.
        ChannelName = PMG.Probe
        ChannelName = ChannelName.replace(' ', '_')
        channelObj = ChannelNode.Create(ChannelName)
        channelObj.SetScale(scaleValueInNm)
        [channelAdded, channelObj] = sectionObj.UpdateOrAddChildByAttrib(channelObj, 'Name')

        channelObj.Initials = PMG.Initials
        channelObj.Mag = PMG.Mag
        channelObj.Spot = PMG.Spot
        channelObj.Slide = PMG.Slide
        channelObj.Block = PMG.Block

        FlipList = GetFlipList(ParentDir)
        Flip = PMG.Section in FlipList

        if(Flip):
            prettyoutput.Log("Flipping")


        # TODO: Add scale element


       # OutFilename = ChannelName + "_supertile.mosaic"
       # OutFilepath = os.path.join(SectionPath, OutFilename)
    
        # Preserve the PMG file
    #            PMGBasename = os.path.basename(filename)
    #            PMGOutputFile = os.path.join(OutputPath, PMGBasename)
    #            ir.RemoveOutdatedFile(filename, PMGOutputFile)
    #            if not os.path.exists(PMGOutputFile):
    #                shutil.copy(filename, PMGOutputFile)
    #
    #            #See if we need to remove the old supertile mosaic
    #            ir.RemoveOutdatedFile(filename, OutFilepath)
    #            if(os.path.exists(OutFilepath)):
    #                continue
    #
        Tiles = ParsePMG(PMGFullPath)
    
        if len(Tiles) == 0:
            raise Exception("No tiles found within PMG file")
    
        NumImages = len(Tiles)
    
        # Create a filter and mosaic
        FilterName = 'Raw' + str(TargetBpp)
        if(TargetBpp is None):
            FilterName = 'Raw'
    
        [added_filter, filterObj] = channelObj.GetOrCreateFilter(FilterName)
        filterObj.BitsPerPixel = TargetBpp
    
        SupertileName = 'Stage'
        SupertileTransform = SupertileName + '.mosaic'
        
        [addedTransform, transformObj] = channelObj.UpdateOrAddChildByAttrib(TransformNode.Create(Name=SupertileName,
                                                                     Path=SupertileTransform,
                                                                     Type='Stage'),
                                                                     'Path')
    
        [added, PyramidNodeObj] = filterObj.UpdateOrAddChildByAttrib(TilePyramidNode.Create(Type='stage',
                                                                                     NumberOfTiles=NumImages),
                                                                                     'Path')
    
        [added, LevelObj] = PyramidNodeObj.UpdateOrAddChildByAttrib(LevelNode.Create(Level=1), 'Downsample')
    
        # Make sure the target LevelObj is verified if it already existed
        if not added and LevelObj.NeedsValidation:
            VerifyTiles(LevelNode=LevelObj)
     
        OutputImagePath = os.path.join(channelObj.FullPath, filterObj.Path, PyramidNodeObj.Path, LevelObj.Path)
    
        os.makedirs(OutputImagePath, exist_ok=True)
    
        InputTileToOutputTile = {}
        PngTiles = {}
        TileKeys = list(Tiles.keys())
    
    
        imageSize = []
        for inputTile in TileKeys:
            [base, ext] = os.path.splitext(inputTile)
            pngMosaicTile = base + '.png'
    
            OutputTileFullPath = os.path.join(LevelObj.FullPath, pngMosaicTile)
            InputTileFullPath = os.path.join(PMGDir, inputTile)
    
            if not os.path.exists(OutputTileFullPath):
                InputTileToOutputTile[InputTileFullPath] = OutputTileFullPath
    
            PngTiles[pngMosaicTile] = Tiles[inputTile]
            (Height, Width) = nornir_imageregistration.GetImageSize(InputTileFullPath)
            imageSize.append((Width, Height))
    
        nornir_imageregistration.ConvertImagesInDict(InputTileToOutputTile, Flip=False, OutputBpp=TargetBpp)
    
        if not os.path.exists(transformObj.FullPath):
            mosaicfile.MosaicFile.Write(transformObj.FullPath, PngTiles, Flip=Flip, ImageSize=imageSize)
    
        return [PMG.Section, ChannelName]

def ParsePMG(filename, TileOverlapPercent=None):

    if TileOverlapPercent is None:
        TileOverlapPercent = 0.1

    # Create a dictionary to store tile position
    Tiles = dict()
    # OutFilepath = os.path.join(SectionPath, OutFilename)

    PMGDir = os.path.dirname(filename)

    if(DEBUG):
        prettyoutput.Log("Filename: " + filename)
        # prettyoutput.Log("PMG to: " + OutFilepath)

    Data = ''
    with open(filename, 'r') as SourceFile:
        Data = SourceFile.read()
        SourceFile.close()

    Data = Data.replace('\r\n', '\n')

    Tuple = Data.partition('VISPIECES')
    Tuple = Tuple[2].partition('\n')
    NumPieces = int(Tuple[0])

    Tuple = Data.partition('VISSCALE')
    Tuple = Tuple[2].partition('\n')
    ScaleFactor = 1 / float(Tuple[0])

    Tuple = Data.partition('IMAGEREDUCTION')
    Tuple = Tuple[2].partition('\n')
    ReductionFactor = 1 / float(Tuple[0])

    Data = Tuple[2]

    if(DEBUG):
        prettyoutput.Log(("Num Tiles: " + str(NumPieces)))
        prettyoutput.Log(("Scale    : " + str(ScaleFactor)))
        prettyoutput.Log(("Reduction: " + str(ReductionFactor)))

    Tuple = Data.partition('PIECE')
    Data = Tuple[2]

    # What type of files did Syncroscan write?  We have to assume BMP and then switch to tif
    # if the BMP's do not exist.
    FileTypeExt = "BMP"

    TileWidth = 0
    TileHeight = 0

    while Data:
        Tuple = Data.partition('ENDPIECE')
        # Remaining unprocessed file goes into data
        Data = Tuple[2]
        Entry = Tuple[0]

        # Find filename
        Tuple = Entry.partition('PATH')

        # Probably means we skipped the last tile in a PMG
        if(Tuple[1] != "PATH"):
            continue

        Tuple = Tuple[2].partition('<')
        Tuple = Tuple[2].partition('>')
        TileFilename = Tuple[0]

        TileFullPath = os.path.join(PMGDir, TileFilename)
        # PMG files for some reason always claim the tile is a .bmp.  So we trust them first and if it doesn't
        # exist we try to find a .tif
        if not  os.path.exists(TileFullPath):
            [base, ext] = os.path.splitext(TileFilename)
            TileFilename = base + '.tif'
            TileFullPath = os.path.join(PMGDir, TileFilename)
            FileTypeExt = 'tif'

        if not os.path.exists(TileFullPath):
            prettyoutput.Log('Skipping missing tile in PMG: ' + TileFilename)
            continue

        if(TileWidth == 0):
            try:
                [TileHeight, TileWidth] = nornir_imageregistration.GetImageSize(TileFullPath)
                if(DEBUG):
                    prettyoutput.Log(str(TileWidth) + ',' + str(TileHeight) + " " + TileFilename)
            except:
                prettyoutput.Log('Could not determine size of tile: ' + TileFilename)
                continue

        # prettyoutput.Log("Adding tile: " + TileFilename)
        # Prevent rounding errors later when we divide these numbers
        TileWidth = float(TileWidth)
        TileHeight = float(TileHeight)

        TileWidthMinusOverlap = TileWidth - (TileWidth * TileOverlapPercent)
        TileHeightMinusOverlap = TileHeight - (TileHeight * TileOverlapPercent)

        # Find Position
        Tuple = Entry.partition('CORNER')
        Tuple = Tuple[2].partition('\n')
        Position = Tuple[0].split()

        # prettyoutput.Log( Position
        X = float(Position[0])
        Y = float(Position[1])

        # Convert Position into pixel units using Reduction and Scale factors
        X = X * ScaleFactor * ReductionFactor
        Y = Y * ScaleFactor * ReductionFactor

        # Syncroscan lays out tiles in grids, so find the nearest grid coordinates of this tile
        # This lets us use the last captured tile per grid cell, so users can manually correct
        # focus
        iX = round(X / TileWidthMinusOverlap)
        iY = round(Y / TileHeightMinusOverlap)

        if(DEBUG):
            prettyoutput.Log(("Name,iX,iY: " + TileFilename + " " + str((iX, iY))))

        # Add tile to dictionary
        # Using the indicies will replace any existing tiles in that location.
        # Syncroscan adds the tiles to the file in order of capture, so the older, blurry
        # tiles will be replaced.

        Tiles[TileFilename] = X, Y

        # Prime for next iteration
        Tuple = Data.partition('PIECE')
        Data = Tuple[2]

    return Tiles

