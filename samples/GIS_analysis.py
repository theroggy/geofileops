
import datetime
import json
import logging
import logging.config
from pathlib import Path
import sys

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo

if __name__ == '__main__':

    # Init 
    start_time = datetime.datetime.now()
    
    script_dir = Path(__file__).resolve().parent
    with open(script_dir / 'logging.json', 'r') as log_config_file:
        log_config_dict = json.load(log_config_file)
    logging.config.dictConfig(log_config_dict)
    logging.raiseExceptions = True
    logger = logging.getLogger()
    
    #input_path=r"X:\Monitoring\OrthoSeg\topobuildings\output_vector\topobuildings_07_BEFL_topo_1969\topobuildings_07_BEFL_topo_1969.gpkg"
    #output_path=r"X:\Monitoring\OrthoSeg\topobuildings\output_vector\topobuildings_07_BEFL_topo_1969\topobuildings_07_BEFL_topo_1969_diss_card.gpkg"
    
    input_path = r"X:\__IT_TEAM_ANG_GIS\Taken\2020\2020-04-09_FasterDissolve\GBG_woningen03.gpkg"
    output_dir = Path(r"X:\__IT_TEAM_ANG_GIS\Taken\2020\2020-04-09_FasterDissolve\testje")
    tiles_path = r"X:\GIS\GIS DATA\Versnijdingen\Kaartbladversnijdingen_NGI_numerieke_reeks_Shapefile\Shapefile\Kbl8.shp"
    tempdir = output_dir / 'Temp'
    
    output_basename = "GBG_woningen03_kbl8"
    verbose = True
    force = True

    # Go!
    logger.info(gfo.get_layerinfo(input_path))
    logger.info("Start dissolve buildings")
    buildings_diss_path = str(tempdir / f"{output_basename}_diss.gpkg")
    gfo.dissolve(
            input_path=input_path,
            tiles_path=tiles_path,
            output_path=buildings_diss_path,
            explodecollections=True,
            clip_on_tiles=True)
    logger.info("Ready dissolve buildings")

    logger.info("Start buffer 50m")
    buildings_diss_buf50m_path = str(tempdir / f"{output_basename}_diss_buf50m.gpkg")
    gfo.buffer(
            input_path=buildings_diss_path,
            output_path=buildings_diss_buf50m_path,
            distance=50)
    logger.info("Ready buffer 50m")

    logger.info("Start dissolve buffer 50m")
    buildings_diss_buf50m_diss_path = str(output_dir / f"{output_basename}_diss_buf50m_diss.gpkg")
    gfo.dissolve(
            input_path=buildings_diss_buf50m_path,
            tiles_path=tiles_path,
            output_path=buildings_diss_buf50m_diss_path,
            explodecollections=True,
            clip_on_tiles=True)
    logger.info("Ready dissolve buffer 50m")

    logger.info("Start buffer 100m")
    buildings_diss_buf100m_path = str(tempdir / f"{output_basename}_diss_buf100m.gpkg")
    gfo.buffer(
            input_path=buildings_diss_path,
            output_path=buildings_diss_buf100m_path,
            distance=100)
    logger.info("Ready buffer 100m")

    logger.info("Start dissolve buffer 100m")
    buildings_diss_buf100m_diss_path = str(output_dir / f"{output_basename}_diss_buf100m_diss.gpkg")
    gfo.dissolve(
            input_path=buildings_diss_buf100m_path,
            tiles_path=tiles_path,
            output_path=buildings_diss_buf100m_diss_path,
            explodecollections=True,
            clip_on_tiles=True)
    logger.info("Ready dissolve buffer 100m")

    logger.info(f"Processing ready, total time was {datetime.datetime.now()-start_time}!")
    