'''
Created on Feb 25, 2014

@author: James Anderson
'''

import logging
import math
import nornir_buildmanager
import nornir_buildmanager.volumemanager
import nornir_shared.prettyoutput


def SetFilterLock(Node, Locked, **kwargs):
    LockChanged = False
    ParentFilter = Node 
    if not isinstance(Node, nornir_buildmanager.volumemanager.FilterNode):
        ParentFilter = Node.FindParent('Filter')
    
    if not ParentFilter is None:
        LockChanged = ParentFilter.Locked != bool(Locked)
        ParentFilter.Locked = bool(Locked)
    else:
        nornir_shared.prettyoutput.LogErr("Unable to find filter for node {0}".format(str(Node)))
    
    if LockChanged:
        return ParentFilter.Parent
    
    return
        
        
def SetLocked(Node, Locked, **kwargs):
    LockChanged = Node.Locked != bool(Locked)
    if LockChanged:
        Node.Locked = bool(Locked)
        parent = Node.Parent
        if not parent is None:
            return parent
    else:
        return
    
def ForceUpdateInputTransformNode(Node: nornir_buildmanager.volumemanager.TransformNode, **kwargs):
    transform = Node
    parent = Node.Parent
    if transform.HasInputTransform is False:
        return
    
    input_transform = parent.GetChildByAttrib('Transform', 'Name', transform.InputTransform)
    if input_transform is not None:
        transform.SetTransform(input_transform)
        nornir_shared.prettyoutput.Log(f"Updated input transform for {transform.FullPath} to {input_transform.Checksum}")
        return parent
    
    return
    

def SetPruneThreshold(PruneNode, Value, **kwargs):

    logger = logging.getLogger(__name__ + '.SetPruneThreshold')

    PruneNode.UserRequestedCutoff = str(Value)

    SetFilterLock(PruneNode, False)

    logger.info("Set Prune Threshold to %g on %s" % (Value, PruneNode.Parent.FullPath))

    return PruneNode.FindParent('Filter').Parent


def SetContrastRange(HistogramElement, MinValue, MaxValue, GammaValue, **kwargs):

    logger = logging.getLogger(__name__ + '.SetContrastRange')

    if math.isnan(MinValue):
        minStr = "Default/Unchanged"
    else:
        minStr = MinValue

    if math.isnan(MaxValue):
        maxStr = "Default/Unchanged"
    else:
        maxStr = MaxValue

    if math.isnan(GammaValue):
        gammaStr = "Default/Unchanged"
    else:
        gammaStr = GammaValue

    AutoLevelHint = HistogramElement.GetOrCreateAutoLevelHint()

    if not math.isnan(MinValue):
        AutoLevelHint.UserRequestedMinIntensityCutoff = float(MinValue)
    if not math.isnan(MaxValue):
        AutoLevelHint.UserRequestedMaxIntensityCutoff = float(MaxValue)
    if not math.isnan(GammaValue):
        AutoLevelHint.UserRequestedGamma = GammaValue

    SetFilterLock(AutoLevelHint, False)

    logger.info("Set contrast min: %s max: %s, gamma: %s on %s" % (minStr, maxStr, gammaStr, HistogramElement.Parent.FullPath))

    return HistogramElement.Parent


def PrintContrast(FilterElement, **kwargs):
    
    ChannelElement = FilterElement.FindParent('Channel')
    SectionElement = FilterElement.FindParent('Section')
    
    minI = FilterElement.MinIntensityCutoff
    maxI = FilterElement.MaxIntensityCutoff
    gamma = FilterElement.Gamma
    
    if minI is None:
        minI = float('nan')
        
    if maxI is None:
        maxI = float('nan')
        
    if gamma is None:
        gamma = float('nan')
    
    output = ("{0:s}{1:s}{2:s}{3:s}{4:s}{5:s}".format(("{0:d}".format(SectionElement.Number)).ljust(6),
                                                    ChannelElement.Name.ljust(16), FilterElement.Name.ljust(16),
                                                    ("{0:g}".format(minI)).ljust(8),
                                                    ("{0:g}".format(maxI)).ljust(8),
                                                    ("{0:g}".format(gamma)).ljust(8)))
    
    print(output)
    return 

       
def SetFilterContrastLocked(FilterNode, Locked, **kwargs):

    logger = logging.getLogger(__name__ + '.SetFilterContrastLocked')

    LockChanged = FilterNode.Locked != bool(int(Locked))
    if LockChanged:
        FilterNode.Locked = bool(int(Locked))
        logger.info("Setting filter to locked = " + str(Locked) + "  " + FilterNode.FullPath)
        return FilterNode.Parent


def SetFilterMaskName(FilterNode, MaskName, **kwargs):
    
    logger = logging.getLogger(__name__ + '.SetFilterContrastLocked')

    FilterNode.MaskName = MaskName

    logger.info("Setting filter MaskName to " + MaskName + "  " + FilterNode.FullPath)

    yield FilterNode.Parent


def PrintSectionsDamaged(block_node, **kwargs):
    print(','.join(list(map(str, block_node.NonStosSectionNumbers))))
    return


def MarkSectionsAsDamaged(block_node, SectionNumbers, **kwargs):
    block_node.MarkSectionsAsDamaged(SectionNumbers)
    return block_node.Parent

    
def MarkSectionsAsUndamaged(block_node, SectionNumbers, **kwargs):
    block_node.MarkSectionsAsUndamaged(SectionNumbers)
    return block_node.Parent


if __name__ == '__main__':
    pass
