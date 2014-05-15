nornir-build Assemble -volume %1 -Filters LeveledShadingCorrected -Downsample 2 -NoInterlace -Transform Grid 
nornir-build CreateBlobFilter -volume %1  -InputFilter LeveledShadingCorrected -OutputFilter Blob -Levels 2,4,8 -Radius 7 -Median 5 -Max 3
nornir-build AlignSections -volume %1  -Downsample 8 -Filters Blob
nornir-build RefineSectionAlignment -volume %1  -Filters LeveledShadingCorrected -InputGroup StosBrute -InputDownsample 8 -OutputGroup Grid -OutputDownsample 8
nornir-build RefineSectionAlignment -volume %1  -Filters LeveledShadingCorrected -InputGroup Grid -AlignFilters ShadingCorrected -InputDownsample 8 -OutputGroup Grid -OutputDownsample 2
nornir-build ScaleVolumeTransforms -volume %1  -InputGroup Grid -InputDownsample 2 -OutputDownsample 1
nornir-build SliceToVolume -volume %1  -InputDownsample 1 -InputGroup Grid -OutputGroup SliceToVolume
nornir-build MosaicToVolume -volume %1  -InputTransform Grid -OutputTransform ChannelToVolume
nornir-build Assemble -volume %1  -ChannelPrefix Registered_ -Filter ShadingCorrected -Downsample 1 -Output %1_Registered -NoInterlace -Transform ChannelToVolume -Channels (?!Registered)
nornir-build ExportImages -volume %1  -Channels Registered -Filters ShadingCorrected -Downsample 1 -Output %1_Registered
