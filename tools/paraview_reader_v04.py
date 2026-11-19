"""Optional validation with an installed ParaView pvpython interpreter.

Run:
  pvpython tools/paraview_reader_v04.py /absolute/path/model.vtm
"""
import sys
from paraview.simple import OpenDataFile, UpdatePipeline
from paraview import servermanager
from vtkmodules.vtkCommonDataModel import vtkMultiBlockDataSet

path=sys.argv[1]
reader=OpenDataFile(path)
if reader is None:
    raise RuntimeError("ParaView could not create VTK reader")
UpdatePipeline(proxy=reader)
data=servermanager.Fetch(reader)
print("VTK_CLASS",data.GetClassName())
assert isinstance(data,vtkMultiBlockDataSet)
print("BLOCKS",data.GetNumberOfBlocks())
assert data.GetNumberOfBlocks()>=3
count=0
for index in range(data.GetNumberOfBlocks()):
    block=data.GetBlock(index)
    if block is None:
        continue
    print("BLOCK",index,block.GetClassName(),block.GetNumberOfCells())
    assert block.GetNumberOfCells()>0
    count+=1
assert count>=3
print("PASS: ParaView read the complete 3D model scene")
