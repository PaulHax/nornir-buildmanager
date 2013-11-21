import copy
import logging
import math
import os.path

from nornir_buildmanager import VolumeManagerETree
from nornir_buildmanager.validation import transforms
from nornir_imageregistration.image_stats import Prune
from nornir_imageregistration.files import mosaicfile
from nornir_shared.files import RemoveOutdatedFile
from nornir_shared.histogram import Histogram
import nornir_shared.misc
import nornir_shared.plot as plot
import nornir_shared.prettyoutput as prettyoutput


class PruneObj:
    """Executes ir-prune and produces a histogram"""

    ImageMapFileTemplate = "PruneScores%s.txt"

    HistogramXMLFileTemplate = 'PruneScores%s.xml'
    HistogramPNGFileTemplate = 'PruneScores%s.png'

    ElementVersion = 1

    def __init__(self, MapToImageScore=None, Tolerance=None):
        self.Tolerance = Tolerance
        if(self.Tolerance is None):
            self.Tolerance = 5

        if(MapToImageScore is None):
            self.MapImageToScore = dict()
        else:
            self.MapImageToScore = MapToImageScore


    @classmethod
    def PruneMosaic(cls, Parameters, PruneNode, TransformNode, OutputTransformName=None, Logger=None, **kwargs):
        '''@ChannelNode 
           Uses a PruneData node to prune the specified mosaic file'''

        if(Logger is None):
            Logger = logging.getLogger('PruneMosaic')

        Threshold = Parameters.get('Threshold', 0.0)
        if Threshold is None:
            Threshold = 0.0

        if not PruneNode.UserRequestedCutoff is None:
            Threshold = PruneNode.UserRequestedCutoff

        if OutputTransformName is None:
            OutputTransformName = 'Prune'

        InputTransformNode = TransformNode
        TransformParent = InputTransformNode.Parent

        OutputMosaicName = OutputTransformName + nornir_shared.misc.GenNameFromDict(Parameters) + '.mosaic'

        MangledName = nornir_shared.misc.GenNameFromDict(Parameters)
        ImageMapFile = PruneObj.ImageMapFileTemplate % MangledName

        HistogramXMLFile = PruneObj.HistogramXMLFileTemplate % PruneNode.Type
        HistogramPNGFile = PruneObj.HistogramPNGFileTemplate % PruneNode.Type

        MosaicDir = os.path.dirname(InputTransformNode.FullPath)
        OutputMosaicFullPath = os.path.join(MosaicDir, OutputMosaicName)

        # Check if there is an existing prune map, and if it exists if it is out of date
        PruneNodeParent = PruneNode.Parent

        TransformParent.RemoveOldChildrenByAttrib('Transform', 'Name', OutputTransformName)

        OutputTransformNode = TransformParent.GetChildByAttrib('Transform', 'Name', OutputTransformName)
        OutputTransformNode = transforms.RemoveIfOutdated(OutputTransformNode, TransformNode, Logger)
        OutputTransformNode = transforms.RemoveOnMismatch(OutputTransformNode, 'Threshold', Threshold, Precision=3)

        # Add the Prune Transform node if it is missing
        if OutputTransformNode is None:
            OutputTransformNode = VolumeManagerETree.TransformNode(Name=OutputTransformName, Type=MangledName, InputTransformChecksum=InputTransformNode.Checksum)
            TransformParent.append(OutputTransformNode)
        elif os.path.exists(OutputTransformNode.FullPath):
            # The meta-data and output exist, do nothing
            return None


        OutputTransformNode.InputTransform = InputTransformNode.Name
        OutputTransformNode.InputPruneDataType = PruneNode.Type
        OutputTransformNode.InputTransformChecksum = InputTransformNode.Checksum
        if not Threshold is None:
            OutputTransformNode.Threshold = str(Threshold)

        PruneDataNode = PruneNode.find('Data')
        if(PruneDataNode is None):
            Logger.warning("Did not find expected prune data node")
            return None

        PruneObjInstance = cls.ReadPruneMap(PruneDataNode.FullPath)
        PruneObjInstance.Tolerance = Threshold

        assert(not PruneObjInstance is None)

        PruneObjInstance.HistogramXMLFileFullPath = os.path.join(PruneNodeParent.FullPath, HistogramXMLFile)
        PruneObjInstance.HistogramPNGFileFullPath = os.path.join(PruneNodeParent.FullPath, HistogramPNGFile)

        try:
            RemoveOutdatedFile(PruneDataNode.FullPath, PruneObjInstance.HistogramPNGFileFullPath)
            RemoveOutdatedFile(PruneDataNode.FullPath, PruneObjInstance.HistogramXMLFileFullPath)

            HistogramNode = PruneNode.find('Image')
            if not HistogramNode is None:
                HistogramNode = transforms.RemoveOnMismatch(HistogramNode, 'Threshold', Threshold, Precision=3)

            if HistogramNode is None or not os.path.exists(PruneObjInstance.HistogramPNGFileFullPath):
                HistogramNode = VolumeManagerETree.ImageNode(HistogramPNGFile)
                (added, HistogramNode) = PruneNode.UpdateOrAddChild(HistogramNode)
                HistogramNode.Threshold = '%g' % Threshold
                PruneObjInstance.CreateHistogram(PruneObjInstance.HistogramXMLFileFullPath,
                                                 PruneObjInstance.HistogramPNGFileFullPath,
                                                 Title="Threshold " + str(Threshold))
        except Exception as E:
            prettyoutput.LogErr("Exception creating prunemap histogram:" + str(E))
            pass

        if(OutputTransformNode is None):
            if(not hasattr(OutputTransformNode, Threshold)):
                OutputTransformNode.Threshold = Threshold

            if(OutputTransformNode.Threshold != Threshold):
                if(os.path.exists(OutputMosaicFullPath)):
                    os.remove(OutputMosaicFullPath)

        if not os.path.exists(OutputMosaicFullPath):
            PruneObjInstance.WritePruneMosaic(PruneNodeParent.FullPath, InputTransformNode.FullPath, OutputMosaicFullPath, Tolerance=Threshold)

        OutputTransformNode.Type = MangledName
        OutputTransformNode.Name = OutputTransformName
        OutputTransformNode.Threshold = Threshold
        OutputTransformNode.Checksum = mosaicfile.MosaicFile.LoadChecksum(OutputTransformNode.FullPath)
        return [TransformParent, PruneNodeParent]

    @classmethod
    def CalculatePruneScores(cls, Parameters, FilterNode, LevelNode, TransformNode, OutputFile=None, Logger=None, **kwargs):
        '''@FilterNode
            Calculate the prune scores for a filter and level'''
        # VolumeManager.NodeManager.GetParent(Entry.NodeList)
        # Check for an existing prune map

        Overlap = float(Parameters.get('Overlap', 0.1))

        if OutputFile is None:
            OutputFile = 'PruneScores'

        if(LevelNode is None):
            prettyoutput.LogErr("Missing InputPyramidLevelNode attribute on PruneTiles")
            Logger.error("Missing InputPyramidLevelNode attribute on PruneTiles")
            return

        if(TransformNode is None):
            prettyoutput.LogErr("Missing TransformNode attribute on PruneTiles")
            Logger.error("Missing TransformNode attribute on PruneTiles")
            return

        FilterNode = LevelNode.FindParent("Filter")

        # Record the downsample level the values are calculated at:
        Parameters['Level'] = str(LevelNode.Downsample)
        Parameters['Filter'] = FilterNode.Name

        MangledName = nornir_shared.misc.GenNameFromDict(Parameters) + '_' + TransformNode.Type
        OutputFile = OutputFile + MangledName + '.txt'

        SaveRequired = False
        PruneMapElement = FilterNode.GetChildByAttrib('Prune', 'Overlap', Overlap)
        PruneMapElement = transforms.RemoveOnMismatch(PruneMapElement, 'InputTransformChecksum', TransformNode.Checksum)

        if not PruneMapElement is None:
            if hasattr(LevelNode, 'TilesValidated'):
                PruneMapElement = transforms.RemoveOnMismatch(PruneMapElement, 'NumImages', LevelNode.TilesValidated)

        if PruneMapElement is None:
            PruneMapElement = VolumeManagerETree.PruneNode(Overlap=Overlap, Type=MangledName)
            [SaveRequired, PruneMapElement] = FilterNode.UpdateOrAddChildByAttrib(PruneMapElement, 'Overlap')
        else:
            # If meta-data and the data file exist, nothing to do
            if os.path.exists(PruneMapElement.DataFullPath):
                return None

        # Create file holders for the .xml and .png files
        PruneDataNode = VolumeManagerETree.DataNode(OutputFile)
        [added, PruneDataNode] = PruneMapElement.UpdateOrAddChild(PruneDataNode)

        FullTilePath = LevelNode.FullPath

        TransformObj = mosaicfile.MosaicFile.Load(TransformNode.FullPath)
        TransformObj.RemoveInvalidMosaicImages(FullTilePath)

        files = []
        for f in TransformObj.ImageToTransformString.keys():
            files.append(os.path.join(FullTilePath, f))

        TileToScore = Prune(files, Overlap)

        prune = PruneObj(TileToScore)

        prune.WritePruneMap(PruneDataNode.FullPath)

        PruneMapElement.InputTransformChecksum = TransformNode.Checksum
        PruneMapElement.NumImages = len(TileToScore)

        return FilterNode
#
    def WritePruneMap(self, MapImageToScoreFile):

        if len(self.MapImageToScore) == 0:
            prettyoutput.LogErr('No prune scores to write to file ' + MapImageToScoreFile)
            return

        with open(MapImageToScoreFile, 'w') as outfile:

            if(len(self.MapImageToScore.keys()) == 0):
                if(os.path.exists(MapImageToScoreFile)):
                    os.remove(MapImageToScoreFile)

                prettyoutput.Log("No prune scores present in PruneMap being saved: " + MapImageToScoreFile)
                outfile.close()
                return

            for f in sorted(self.MapImageToScore.keys()):
                score = self.MapImageToScore[f]

                outfile.write(f + '\t' + str(score) + '\n')

            outfile.close()

    @classmethod
    def ReadPruneMap(cls, MapImageToScoreFile):

        assert(os.path.exists(MapImageToScoreFile))
        infile = open(MapImageToScoreFile, 'r')
        lines = infile.readlines()
 #      prettyoutput.Log( lines)
        infile.close()

        assert(len(lines) > 0)
        if(len(lines) == 0):
            return None

        MapImageToScore = dict()

        for line in lines:
            [image, score] = line.split('\t')
            score = float(score.strip())

            MapImageToScore[image] = score

        return PruneObj(MapImageToScore)

    def CreateHistogram(self, HistogramXMLFile, HistogramImageFile, MapImageToScoreFile=None, Title=None):
        if(len(self.MapImageToScore.items()) == 0 and MapImageToScoreFile is not None):
   #         prettyoutput.Log( "Reading scores, MapImageToScore Empty " + MapImageToScoreFile)
            PruneObj.ReadPruneMap(self, MapImageToScoreFile)
   #         prettyoutput.Log( "Read scores complete: " + str(self.MapImageToScore))

        if Title is None:
            Title = "Prune Map"

        if(len(self.MapImageToScore.items()) == 0):
            prettyoutput.Log("No prune scores to create histogram with")
            return



        scores = [None] * len(self.MapImageToScore.items())
        numScores = len(scores)

        i = 0
        for pair in self.MapImageToScore.items():
   #         prettyoutput.Log("pair: " + str(pair))
            scores[i] = pair[1]
            i = i + 1

        # Figure out what type of histogram we should create
 #       prettyoutput.Log('Scores: ' + str(scores))
        minVal = min(scores)
        # prettyoutput.Log("MinVal: " + str(minVal))
        maxVal = max(scores)
        # prettyoutput.Log("MaxVal: " + str(maxVal))
        mean = sum(scores) / len(scores)

        # prettyoutput.Log("Mean: " + str(mean))

        StdDevScalar = 1 / float(numScores - 1)
        total = 0
        # Calc the std deviation
        for score in scores:
            temp = score - mean
            temp = temp * temp
            total = total + (temp * StdDevScalar)

        StdDev = math.sqrt(total)
        # prettyoutput.Log("StdDev: " + str(StdDev))

        numBins = int(math.ceil((maxVal - minVal) / (StdDev / 10)))

        # prettyoutput.Log("NumBins: " + str(numBins))

        if(numBins < 10):
            numBins = 10

        if(numBins > len(scores)):
            numBins = len(scores)

        # prettyoutput.Log("Final NumBins: " + str(numBins))

        H = Histogram.Init(minVal, maxVal, numBins)
        H.Add(scores)
        H.Save(HistogramXMLFile)

        plot.Histogram(HistogramXMLFile, HistogramImageFile, LinePosList=self.Tolerance, Title=Title)


    def WritePruneMosaic(self, path, SourceMosaic, TargetMosaic='prune.mosaic', Tolerance='5'):
        '''
        Remove tiles from the source mosaic with scores less than Tolerance and
        write the new mosaic to TargetMosaic
        '''

        if(not isinstance(Tolerance, float)):
            Tolerance = float(Tolerance)

        SourceMosaicFullPath = os.path.join(path, SourceMosaic)
        TargetMosaicFullPath = os.path.join(path, TargetMosaic)

        mosaic = mosaicfile.MosaicFile.Load(SourceMosaicFullPath)

        # We copy this because if an input image is missing there will not be a prune score and it should be removed from the .mosaic file
        inputImageToTransforms = copy.deepcopy(mosaic.ImageToTransformString)
        mosaic.ImageToTransformString.clear()

        numRemoved = 0

        for item in self.MapImageToScore.items():
            filename = item[0]
            score = item[1]

            if(score >= Tolerance):
                keyVal = filename
                if not keyVal in inputImageToTransforms:
                    keyVal = os.path.basename(filename)
                    if not keyVal in inputImageToTransforms:
                        raise KeyError ("PruneObj: Cannot locate image file in .mosaic " + keyVal)

                mosaic.ImageToTransformString[keyVal] = inputImageToTransforms[keyVal]
            else:
                numRemoved = numRemoved + 1

        if(len(mosaic.ImageToTransformString) <= 0):
            prettyoutput.LogErr("All tiles removed when using threshold = " + str(Tolerance) + "\nThe prune request was ignored")
            return
        else:
            prettyoutput.Log("Removed " + str(numRemoved) + " tiles pruning mosaic " + TargetMosaic)

        mosaic.Save(TargetMosaicFullPath)

        return numRemoved

if __name__ == "__main__":

    XmlFilename = 'D:\Buildscript\Pipelines.xml'
    PipelineManager.Load(XmlFilename)

