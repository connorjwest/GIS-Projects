import arcpy
import time
import sys

# BUILD DATE 10/14/2021
# CHANGELOG 10/14/2021
#   +Re-enabled DEM Filling
#   +SPLIT THE STORM SURGE OUT OF THIS SCRIPT. IT IS NOW LOCATED IN THE SAME TOOLBOX AS STORMSURGEGEN.py
#   +Turned the force stream network/flow accumulation export option in a toggleable option in the arcgis tool interface
#   +Cleaned up the documentation
# CHANGELOG 10/12/2021
#   +Fixed clipping issue for real (switched from clip to extract by mask)
#   +Rewrote storm surge into a function
#   +Added code to force export stream networks and flow accumulation
# CHANGELOG 10/11/2021
#   +Fixed clipping issue
#   +Fixed raster to polygon issue
#   +HARD DISABLED FILLING DEM
# CHANGELOG 10/5/2021:
#   +Added more in-depth comments
#   +Added functionality to check ArcHydro version/compatibility
#   +Added half meter increments to the HAND and Storm Surge models from 0-2 and 0-5 meters, respectively.

# This script is designed to be run as a tool in ArcGIS Pro.
# If you're adding this script to your own toolbox, use lines 45-48 (or search the code for GetParameterAsText) and be sure
# that the parameters in the ArcGIS Tool window match the parameters in the code.

# For more info on what a Height Above Nearest Drainage model is, see the original paper on the subject by Nobre et. al in
# the Journal of Hydrology, Volume 404, Issues 1-2, 20 June 2011, Pages 13-29.

# We start a timer the second the program runs so we can calculate how long the program took
startTime = time.time()

# We also check out some ArcGIS extensions to use some of the SA and IA tools.
# If we didn't do this, they'd have to be checked out/in on every tool call which is horribly slow and inefficient.
arcpy.CheckOutExtension("spatial")
arcpy.CheckOutExtension("ImageAnalyst")

# It's very important the user has the latest version of Arc Hydro Tools Pro, or at least a version of AHTP that
# plays nice with the kind of functions we need to deal with. This script was designed for AHTP 2.8.13, and anything
# before this version throws a very weird error when we try this command
# So, let's try this command, and if we get a RunTimeError we can yell at the user to update their AHTP
try:
    arcpy.AddToolbox(r"C:\Program Files\ArcGIS\Pro\Resources\ArcToolBox\toolboxes\Arc_Hydro_Tools_Pro.tbx")
except RuntimeError:
    arcpy.AddMessage("ERROR: Failed to add ArcHydro Tools Pro. Is it installed in the default location (Program Files) and a compatible version (at least 2.8.13)?")
    arcpy.AddMessage("NOTE: If you have ArcHydro Tools Pro installed in a custom location, edit the AddToolbox command at the start of this tool to the path of the Arc_Hydro_Tools_Pro.tbx file in your installation directory.")
    sys.exit(2)

# Gathering variables. SRTM is the default DEM so most variables reference it (see below) as legacy, but any DEM can
# be used as we'll see in a bit. These getparams gather the user's inputs from the tool menu
SRTM = arcpy.GetParameterAsText(0)  # Should be a RASTER of a DEM/DSM/DTM. Does not need to be hydrologically corrected, but it sure doesn't hurt.
CountryBorder = arcpy.GetParameterAsText(1)  # should be a SHAPEFILE of an area that is covered by the above
scratchSpace = arcpy.GetParameterAsText(2)  # should be a directory into which all products will be exported
streamNetworkThresholdInput = arcpy.GetParameterAsText(3)  # should be a float between 0 and 1 to determine what percentage of accumulation values we take for our stream network
saveStreamNetwork = arcpy.GetParameterAsText(4)  # should be a boolean to determine if we output the stream network

# We confirm this value is a float for ~reasons~ (because it breaks the code if we don't)
strThresh = float(streamNetworkThresholdInput)

# Here we do a little string manipulation in order to get the name of the country we're working with.
# An important caveat here is we are assuming the first three characters of the filename are the ISO three letter country code
CBPath = CountryBorder.split('\\')
CName = CBPath[-1].upper()
CCode = CName[0:3].upper()
arcpy.AddMessage("COUNTRY CODE: " + CCode)

# clip the country out of DEM
arcpy.SetProgressor("default", "Clipping DEM...", 0, 100, 1)

# We don't know what our input DEM is right now, so let's figure that out
# String manipulation of input to find the part we care about
DEMPath = SRTM.split('\\')
DEMName = DEMPath[-1].upper()

# Throw some logic at it to see if we can find any codewords in the filename that will tell us what we're looking at
if DEMName.find("SRTM") != -1:
    DEMName = "SRTM"
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": USING SRTM")
elif DEMName.find("COP") != -1:
    DEMName = "COP"
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": USING COPERNICUS")
elif DEMName.find("WORLD") != -1:
    DEMName = "WORLDDEM"
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": USING WORLDDEM")
else:
    # If we can't find something we recognize just default to the first 4 letters of the filename
    DEMName = DEMName[0:4].upper()
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": USING UNKNOWN DEM " + DEMName)

# Clip the country from the DEM and save it
# We use Extract by Mask rather than Clip Raster here because the latter has some weird behavior with nodata values
# which messes with how we do our conditional statements and hydrological tools
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Clipping " + CCode)
clippedDEM = arcpy.sa.ExtractByMask(SRTM, CountryBorder)
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Complete!")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Saved to " + scratchSpace + CCode + "_" + DEMName + ".tif")

# fill the DEM
arcpy.SetProgressorLabel("Filling DEM...")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Filling " + CCode)
filledDEM = arcpy.sa.Fill(clippedDEM)
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Complete!")

# flow direction and accumulation time
arcpy.SetProgressorLabel("Determining Flow Direction...")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": FlowDIR " + CCode)
flowDir = arcpy.sa.FlowDirection(filledDEM, "NORMAL", "#", "D8")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Complete!")

arcpy.SetProgressorLabel("Determining Flow Accumulation...")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": FlowACC " + CCode)
flowAcc = arcpy.sa.FlowAccumulation(flowDir, "#", "FLOAT", "D8")
if saveStreamNetwork == 'true':
    # If the user enabled the "export stream network" option, we export out the flow accumulation with the DEBUG preamble
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Exporting Flow Accumulation Raster")
    flowAcc.save(scratchSpace + "\\" + "DEBUG_" + CCode + "_" + DEMName + "_FLOWACCUMULATION.tif")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Complete!")

# Generating our stream network. First we need to establish a threshold for our FlowACC raster. Because Arcpy is --
# shall we say -- "unique," we have to get the output of the max of the Flow ACC raster as a Result object first
strThresholdResult = arcpy.GetRasterProperties_management(flowAcc, "MAXIMUM")

# From experience, the nominal value to use for generating a stream network is between 1% and 0.3% of the highest flow accumulation values. We allow the user to set their own threshold to determine the level of detail the stream network contains.
strThreshold = round((int(strThresholdResult.getOutput(0)) * strThresh))

arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Our STR Threshold value is " + str(strThreshold))
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Stream Network")
arcpy.SetProgressorLabel("Creating Stream Network...")
strNetwork = arcpy.ia.Con(flowAcc, 1, "#", "VALUE >= " + str(round(strThreshold)))
if saveStreamNetwork == 'true':
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Exporting Flow Accumulation Raster")
    strNetwork.save(scratchSpace + "\\" + "DEBUG_" + CCode + "_" + DEMName + "_STREAMNETWORK.tif")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Complete!")

# Flow Distance
arcpy.SetProgressorLabel("Completing Flow Distance...")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": FlowDis")
flowDis = arcpy.sa.FlowDistance(strNetwork, filledDEM, flowDir, "VERTICAL", "D8", "MINIMUM")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Complete!")


# Here we do the HAND model. ArcHydro's way of calling tools from it is poorly thought out so I've just reverse
# engineered it
def HANDmodel(FlowDistance, FloodDepth, OutputPolygon, OutputDepthRaster):
    referenceDepth = float(FloodDepth)

    # First step: Con - identify flood extent as raster - this is temporary step - not saving the raster
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": ---- Identifying Flood Extent")
    outExtent = arcpy.sa.Con(arcpy.sa.Raster(FlowDistance) <= referenceDepth, 1)

    # Next: Raster to Polygon - Convert Flood Extent Raster to polygon and attribute
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": ---- Saving flood extent polygon")
    arcpy.RasterToPolygon_conversion(outExtent, r"memory\HAND", "NO_SIMPLIFY", "VALUE")  # We write some of these intermediate steps to memory to save disk space
    arcpy.AddField_management(r"memory\HAND", "FloodValue", "DOUBLE")
    arcpy.CalculateField_management(r"memory\HAND", "FloodValue", referenceDepth, "PYTHON_9.3")
    arcpy.SmoothPolygon_cartography(r"memory\HAND", OutputPolygon, "PAEK", "30 Meters")

    # These commented out processes create a raster which calculates estimated flood depth.
    # While this can be useful for identifying certain important aspects of inundation,
    # it takes a ton of time to generate and is not used in any of our primary analyses.
    # Uncomment these lines if you want to create them. I may possibly add a toolbox option in the future.

    # Process: Raster Calculator
    # arcpy.AddMessage(time.strftime("%H:%M:%S") + ": ---- Calculating flood depth")
    # outDepth = arcpy.sa.Con(outExtent, referenceDepth - arcpy.sa.Raster(FlowDistance))

    # Process: Save output rasters
    # arcpy.AddMessage(time.strftime("%H:%M:%S") + ": ---- Saving flood depth raster")
    # outDepth.save(OutputDepthRaster)
    # arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Saved to " + OutputDepthRaster)

    # Clean
    arcpy.AddMessage(time.strftime("%H:%M:%S") + ": ---- Cleaning")
    arcpy.Delete_management(outExtent)


# Let's call the HANDmodel function we just made to create our 0.5-2.0 meter hand models in 0.5 meter increments

arcpy.SetProgressorLabel("0.5 Meter HAND Model...")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": HAND model")
HANDmodel(flowDis, 0.5, scratchSpace + "\\" + CCode + "_HAND_0_5m_" + DEMName + ".shp",
          scratchSpace + "\\" + CCode + "_HAND_0_5M_" + DEMName + ".tif")

arcpy.SetProgressorLabel("1.0 Meter HAND Model...")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": HAND model")
HANDmodel(flowDis, 1, scratchSpace + "\\" + CCode + "_HAND_1_0m_" + DEMName + ".shp",
          scratchSpace + "\\" + CCode + "_HAND_1_0M_" + DEMName + ".tif")

arcpy.SetProgressorLabel("1.5 Meter HAND Model...")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": HAND model")
HANDmodel(flowDis, 1.5, scratchSpace + "\\" + CCode + "_HAND_1_5m_" + DEMName + ".shp",
          scratchSpace + "\\" + CCode + "_HAND_1_5M_" + DEMName + ".tif")

arcpy.SetProgressorLabel("2.0 Meter HAND Model...")
HANDmodel(flowDis, 2, scratchSpace + "\\" + CCode + "_HAND_2_0m_" + DEMName + ".shp",
          scratchSpace + "\\" + CCode + "_HAND_2_0M_" + DEMName + ".tif")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Complete!")

# returning our extensions
arcpy.CheckInExtension("spatial")
arcpy.CheckInExtension("ImageAnalyst")

# cleaning
arcpy.SetProgressorLabel("Cleaning Up...")
arcpy.AddMessage(time.strftime("%H:%M:%S") + ": Cleaning...")
arcpy.Delete_management(flowDir)
arcpy.Delete_management(filledDEM)
arcpy.Delete_management(flowDis)
if saveStreamNetwork == 'false':
    arcpy.Delete_management(flowAcc)

print("Total time = " + str((time.time() - startTime)) + " seconds.")
