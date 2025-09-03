"""Run the benchmarks specified."""

from benchmark import benchmarker


def main():
    """Run the benchmark function(s)."""
    functions_to_run = [
        # "export_by_location_intersects_complexpoly",
        # "export_by_location_intersects",
        # "join_by_location_intersects",
        # "clip",
        # "intersection",
        # "intersection_complexpoly_agri",
        # "intersection_complexpoly_complexpoly",
        # "intersection_gridsize",
        # "symmetric_difference_complexpolys_agri",
        # "union",
        "buffer_spatialite",
    ]
    # functions_to_run = None
    # Run all benchmark functions
    benchmarker.run_benchmarks(["benchmarks_geofileops"], functions_to_run)


if __name__ == "__main__":
    main()
