
from datetime import datetime
import logging
from pathlib import Path
import sys

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo

logger = logging.getLogger(__name__)

if __name__ == '__main__':

    # Init 
    start_time = datetime.now()
    logging.basicConfig(level=logging.INFO)
    
    input_path = Path(r"X:\__IT_TEAM_ANG_GIS\Taken\2020\2020-04-09_FasterDissolve\GBG_woningen03.gpkg")
    output_dir = Path(r"X:\__IT_TEAM_ANG_GIS\Taken\2020\2020-04-09_FasterDissolve\testje")
    tiles_path = r"X:\GIS\GIS DATA\Versnijdingen\Kaartbladversnijdingen_NGI_numerieke_reeks_Shapefile\Shapefile\Kbl8.shp"
    tmp_dir = output_dir / "Temp"
    output_path = tmp_dir / "GBG_woningen03_kbl8.gpkg"
    force = False

    # Go!
    buildings_diss_path = tmp_dir / f"{input_path.stem}_diss.gpkg"
    gfo.dissolve(
            input_path=input_path,
            tiles_path=tiles_path,
            output_path=buildings_diss_path,
            explodecollections=True)

    buildings_diss_buf50m_path = tmp_dir / f"{buildings_diss_path.stem}_buf50m.gpkg"
    gfo.buffer(
            input_path=buildings_diss_path,
            output_path=buildings_diss_buf50m_path,
            distance=50)

    buildings_diss_buf50m_diss_path =  tmp_dir / f"{buildings_diss_path.stem}_buf50m_diss.gpkg"
    gfo.dissolve(
            input_path=buildings_diss_buf50m_path,
            tiles_path=tiles_path,
            output_path=buildings_diss_buf50m_diss_path,
            explodecollections=True)

    buildings_diss_buf100m_path = tmp_dir / f"{buildings_diss_path.stem}_buf100m.gpkg"
    gfo.buffer(
            input_path=buildings_diss_path,
            output_path=buildings_diss_buf100m_path,
            distance=100)

    buildings_diss_buf100m_diss_path = tmp_dir / f"{buildings_diss_path.stem}_buf100m_diss.gpkg"
    gfo.dissolve(
            input_path=buildings_diss_buf100m_path,
            tiles_path=tiles_path,
            output_path=buildings_diss_buf100m_diss_path,
            explodecollections=True)

    logger.info(f"Processing ready, total time was {datetime.now()-start_time}!")
    