"""Run the benchmarks specified."""

from benchmark import benchmarker


def main():
    """Run the benchmark function(s)."""
    functions_to_run = [
        # "buffer_spatialite",
        # "clip",
        # "clip_agri_complexpoly",
        "dissolve_nogroupby",
        "dissolve_groupby",
        # "export_by_location_intersects_complexpoly",
        # "export_by_location_intersects",
        # "intersection",
        # "intersection_complexpoly_agri",
        # "intersection_complexpoly_complexpoly",
        # "intersection_gridsize",
        # "join_by_location_intersects",
        # "symmetric_difference_complexpolys_agri",
        # "union",
    ]
    # Run all benchmark functions
    # functions_to_run = None
    benchmarker.run_benchmarks(["benchmarks_geofileops"], functions_to_run)


if __name__ == "__main__":
    main()
