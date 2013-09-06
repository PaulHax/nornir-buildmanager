'''
Created on Aug 27, 2013

@author: u0490822
'''

import sys
from nornir_buildmanager import *
from nornir_buildmanager.VolumeManagerETree import *
from nornir_imageregistration.io import  mosaicfile
import subprocess
from nornir_shared.histogram import Histogram
from nornir_shared import *
from nornir_shared.files import RemoveOutdatedFile
import math
import xml
from nornir_imageregistration.transforms import *
from nornir_buildmanager.validation import transforms
from nornir_shared.misc import SortedListFromDelimited

def CreateBlobFilter(Parameters, Logger, InputFilter, **kwargs):
    '''@FilterNode.  Create  a new filter which has been processed with blob'''
    Radius = Parameters.get('r', '3')
    Median = Parameters.get('median', '3')
    Max = Parameters.get('max', '3')

    if hasattr(ImageSetNode, 'Type'):
        MangledName = misc.GenNameFromDict(Parameters) + ImageSetNode.Type
    else:
        MangledName = misc.GenNameFromDict(Parameters)

    ArgString = misc.ArgumentsFromDict(Parameters)

    PyramidLevels = nornir_shared.misc.SortedListFromDelimited(kwargs.get('Levels', [1, 2, 4, 8, 16, 32, 64, 128, 256]))

    ###########################################
    # STOPPED HERE.  NEED TO CREATE A FILTER  #
    ###########################################
    SaveFilterNode = False
    (SaveFilterNode, OutputFilterNode) = InputFilter.Parent.UpdateOrAddChildByAttrib(FilterNode(Name="Blob_" + InputFilter.Name), "Name")

    # DownsampleSearchTemplate = "Level[@Downsample='%(Level)d']/Image"

    OutputBlobName = OutputFilterNode.Name + '.png'

    BlobImageSet = OutputFilterNode.Imageset

    # OutputImageSet.

    # BlobSetNode = VolumeManagerETree.ImageSetNode('blob', MangledName, 'blob', {'MaskName' :  ImageSetNode.MaskName})
    # [added, BlobSetNode] = FilterNode.UpdateOrAddChildByAttrib(BlobSetNode, 'Path')
    # BlobSetNode.MaskName = ImageSetNode.MaskName

    if not os.path.exists(BlobImageSet.FullPath):
        os.makedirs(BlobImageSet.FullPath)

    # BlobSetNode.Type = ImageSetNode.Type + '_' + MangledName

    irblobtemplate = 'ir-blob ' + ArgString + ' -sh 1 -save %(OutputImageFile)s -load %(InputFile)s '

    thisLevel = PyramidLevels[0]

    # DownsampleSearchString = DownsampleSearchTemplate % {'Level': thisLevel}
    # InputMaskLevelNode = MaskSetNode.find(DownsampleSearchString)

    InputImageNode = InputFilter.GetImage(thisLevel)

    if InputImageNode is None:
        prettyoutput.Log("Missing input level nodes for blob level: " + str(thisLevel))
        Logger.warning("Missing input level nodes for blob level: " + str(thisLevel) + ' ' + InputFilter.FullPath)
        return

    InputMaskNode = InputFilter.GetMaskImage(thisLevel)
    MaskStr = ""
    if not InputMaskNode is None:
        OutputFilterNode.MaskName = InputMaskNode.Name
        if not os.path.exists(InputMaskNode.FullPath):
            prettyoutput.Log("Missing input level nodes for blob level: " + str(thisLevel))
            Logger.warning("Missing input level nodes for blob level: " + str(thisLevel) + ' ' + InputFilter.FullPath)
            return

        MaskStr = ' -mask %s ' % InputMaskNode.FullPath

    BlobImageNode = OutputFilterNode.Imageset.GetOrCreateImage(thisLevel, OutputBlobName)

    RemoveOutdatedFile(InputImageNode.FullPath, BlobImageNode.FullPath)

    if not os.path.exists(BlobImageNode.FullPath):

        if not os.path.exists(os.path.dirname(BlobImageNode.FullPath)):
            os.makedirs(os.path.dirname(BlobImageNode.FullPath))

        cmd = irblobtemplate % {'OutputImageFile' : BlobImageNode.FullPath,
                                'InputFile' : InputImageNode.FullPath} + MaskStr

        prettyoutput.Log(cmd)
        subprocess.call(cmd + " && exit", shell=True)
        SaveFilterNode = True

    if(not 'InputImageChecksum' in BlobImageSet):
        BlobImageSet.InputImageChecksum = ImageSetNode.Checksum

    if(not 'InputImageChecksum' in BlobImageNode):
        BlobImageNode.InputImageChecksum = ImageSetNode.Checksum

    if SaveFilterNode:
        return InputFilter.Parent

    return None