"""Module to generate reports for benchmarks."""

import ast
import math
import shutil
import tempfile
from pathlib import Path
from typing import Literal

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pandas.api
from packaging.version import Version
from PIL import Image

A4_LONG_SIDE = 11.69
A4_SHORT_SIDE = 8.27


def generate_reports(results_path: Path, output_dir: Path) -> None:
    """Generate detailed benchmark charts and a library comparison overview."""
    benchmark_df = pd.read_csv(results_path)

    def format_run_details(run_details: object) -> str:
        if run_details is None or pd.isna(run_details):
            return ""
        if isinstance(run_details, str):
            run_details = ast.literal_eval(run_details)
        if isinstance(run_details, dict):
            result_list = [
                f"{key}:{value}" for key, value in run_details.items() if key != "io"
            ]
            return ";".join(result_list)

        return ""

    # Detailed report per package and per operation
    for package in benchmark_df["package"].unique():
        reports_package_dir = output_dir / package
        reports_package_dir.mkdir(parents=True, exist_ok=True)

        package_df = benchmark_df.loc[benchmark_df["package"] == package]
        for operation in package_df["operation"].unique():
            package_operation_df = package_df.loc[
                benchmark_df["operation"] == operation
            ]
            latest_run_datetime = package_operation_df["run_datetime"].max()
            operation_descriptions = package_operation_df.loc[
                package_operation_df["run_datetime"] == latest_run_datetime,
                "operation_descr",
            ].drop_duplicates()
            if len(operation_descriptions) != 1:
                raise ValueError(
                    "Expected one operation description for "
                    f"{package!r}/{operation!r} at run_datetime "
                    f"{latest_run_datetime!r}, found {len(operation_descriptions)}."
                )
            operation_descr = operation_descriptions.iloc[0]
            detail_columns = ["package_version", "run_details", "secs_taken"]
            if "max_memory_bytes" in package_operation_df.columns:
                detail_columns.append("max_memory_bytes")
            package_operation_df = package_operation_df[detail_columns]
            package_operation_df["run_details"] = package_operation_df[
                "run_details"
            ].apply(format_run_details)
            package_operation_df = package_operation_df.set_index(
                ["package_version", "run_details"]
            )
            memory_df = None
            if (
                "max_memory_bytes" in package_operation_df.columns
                and package_operation_df["max_memory_bytes"].notna().any()
            ):
                memory_df = (
                    package_operation_df[["max_memory_bytes"]]
                    .div(1_000_000_000)
                    .rename(columns={"max_memory_bytes": "Max memory (GB)"})
                )
            results_report_path = reports_package_dir / f"{package}_{operation}.png"
            save_chart(
                df=package_operation_df[["secs_taken"]],
                title=f"{package}-{operation}\n({operation_descr})",
                size=(8, 6),
                print_labels_on_points=True,
                y_value_formatter="{0:.2f}",
                output_path=results_report_path,
                secondary_y_df=memory_df,
            )

    # Report for last version of each package+operation for comparison
    benchmark_df["version_suffix"] = benchmark_df["package_version"].apply(
        lambda x: x.split("-")[1] if len(x.split("-")) > 1 else ""
    )
    benchmark_df["version"] = benchmark_df["package_version"].apply(
        lambda x: Version(x.split("-")[0])
    )
    benchmark_maxversions_df = (
        benchmark_df[["package", "operation", "version", "version_suffix"]]
        .sort_values(
            ["package", "operation", "version", "version_suffix"], ascending=False
        )
        .groupby(["package", "operation"])
        .first()
        .reset_index()
        .set_index(["package", "operation", "version", "version_suffix"])
    )
    benchmark_maxversion_df = benchmark_df.set_index(
        ["package", "operation", "version", "version_suffix"]
    )
    comparison_columns = ["secs_taken"]
    if "max_memory_bytes" in benchmark_df.columns:
        comparison_columns.append("max_memory_bytes")
    benchmark_maxversion_df = (
        benchmark_maxversion_df.loc[
            benchmark_maxversion_df.index.isin(benchmark_maxversions_df.index)
        ].reset_index()
    )[
        [
            "package",
            "version",
            "version_suffix",
            "operation",
            *comparison_columns,
        ]
    ]
    # Only keep the last benchmark result value for the same package+operation+version,
    # otherwise pivot_table takes the average seconds
    benchmark_maxversion_df = (
        benchmark_maxversion_df.groupby(
            by=["package", "version", "version_suffix", "operation"]
        )
        .last()
        .reset_index()
    )
    benchmark_maxversion_time_df = benchmark_maxversion_df.pivot_table(
        index="operation",
        columns=["package", "version", "version_suffix"],
        values="secs_taken",
    )
    results_report_path = output_dir / "GeoBenchmark.png"
    save_chart(
        df=benchmark_maxversion_time_df,
        title="Comparison of libraries, time in sec\n",
        output_path=results_report_path,
        yscale="log",
        print_labels_on_points=True,
        point_labels_to_right=True,
        y_value_formatter="{0:.0f}",
        size=(8, 6),
        linestyle="None",
        gridlines="y",
        y_value_limit=10000,
        overflow_axes_top=0.82,
    )

    if (
        "max_memory_bytes" in comparison_columns
        and benchmark_maxversion_df["max_memory_bytes"].notna().any()
    ):
        memory_df = (
            benchmark_maxversion_df.pivot_table(
                index="operation",
                columns=["package", "version", "version_suffix"],
                values="max_memory_bytes",
            )
            / 1_000_000_000
        )
        results_report_path = output_dir / "GeoBenchmark_max_memory.png"
        save_chart(
            df=memory_df,
            title="Comparison of libraries, max memory in GB\n",
            output_path=results_report_path,
            print_labels_on_points=True,
            point_labels_to_right=True,
            y_value_formatter="{0:.2f}",
            size=(8, 6),
            linestyle="None",
            gridlines="y",
        )


def save_chart(
    df: pd.DataFrame,
    title: str,
    output_path: Path,
    *,
    secondary_y_df: pd.DataFrame | None = None,
    yscale: Literal["linear", "log", "symlog", "logit"] | None = None,
    y_value_formatter: str | None = None,
    print_labels_on_points: bool = False,
    point_labels_to_right: bool = False,
    size: tuple[float, float] = (8, 4),
    plot_kind: Literal[
        "line",
        "bar",
        "barh",
        "hist",
        "box",
        "kde",
        "density",
        "area",
        "pie",
        "scatter",
        "hexbin",
    ] = "line",
    gridlines: Literal["both", "x", "y"] | None = None,
    linestyle: str | None = None,
    y_value_limit: float | None = None,
    overflow_axes_top: float = 0.79,
) -> None:
    """Render and save a chart.

    Args:
        df (pd.DataFrame): The data to plot. The index should be the x axis values.
        secondary_y_df (pd.DataFrame, optional): Data to plot on a secondary y axis.
        title (str): The title of the chart.
        output_path (Path): _description_
        yscale (Literal["linear", "log", "symlog", "logit"], optional): y scale to use.
        y_value_formatter (str, optional): a formatter for the y axes and
            labels. Examples:
              - {0:.2%} for a percentage.
              - {0:.2f} for a float with two decimals.
            Defaults to None.
        print_labels_on_points (bool, optional): _description_. Defaults to False.
        point_labels_to_right (bool, optional): place point labels to the right.
            Defaults to False.
        size (Tuple[float, float], optional): _description_. Defaults to (8, 4).
        plot_kind (str, optional): _description_. Defaults to "line".
        gridlines (str, optional): where to draw grid lines:

                - 'x': draw grid lines on the x axis
                - 'y': draw grid lines on the x axis
                - 'both': draw grid lines on both axes
            If None, the default for the style used is used. Defaults to None.
        linestyle (Optional[str], optional): _description_. Defaults to None.
        y_value_limit (float, optional): values above this limit are omitted from
            the plotted series and marked at the top of the chart. Defaults to
            None.
        overflow_axes_top (float, optional): top of the axes when overflow values
            are shown. Defaults to 0.79.

    Raises:
        Exception: _description_
    """
    # Init
    # Check input
    non_numeric_columns = [
        column
        for column in df.columns
        if not pandas.api.types.is_numeric_dtype(df[column])
    ]
    if len(non_numeric_columns) > 0:
        raise Exception(
            f"df has non-numeric columns, so cannot be plotted: {non_numeric_columns}"
        )
    if secondary_y_df is not None and not secondary_y_df.index.equals(df.index):
        raise ValueError("secondary_y_df must have the same index as df.")
    if secondary_y_df is not None:
        non_numeric_columns = [
            column
            for column in secondary_y_df.columns
            if not pandas.api.types.is_numeric_dtype(secondary_y_df[column])
        ]
        if non_numeric_columns:
            raise Exception(
                "secondary_y_df has non-numeric columns, so cannot be plotted: "
                f"{non_numeric_columns}"
            )
    if y_value_limit is not None and (
        not math.isfinite(y_value_limit) or y_value_limit <= 0
    ):
        raise ValueError("y_value_limit must be a positive finite number.")

    # Init some things based on input
    rot = 90

    # Prepare plot figure and axes
    fig, axs = plt.subplots(figsize=(size))
    # Make sure all x axis values are shown
    axs.set_xticks(range(len(df)))
    if yscale is not None:
        plt.yscale(yscale)

    # Plot
    plot_df = df
    if y_value_limit is not None:
        plot_df = df.where(df <= y_value_limit)
    plot_df.plot(
        ax=axs,
        kind=plot_kind,
        rot=rot,
        title=title,
        linestyle=linestyle,
        legend=False,
    )
    secondary_ax = None
    if secondary_y_df is not None:
        secondary_ax = axs.twinx()
        secondary_y_df.plot(
            ax=secondary_ax,
            kind=plot_kind,
            rot=rot,
            linestyle="--",
            legend=False,
        )
        secondary_ax.set_ylabel("Max memory (GB)")
    tick_positions = axs.get_xticks()
    tick_labels = [tick.get_text().replace("_", "\n") for tick in axs.get_xticklabels()]
    axs.set_xticks(tick_positions)
    axs.set_xticklabels(tick_labels, rotation=rot)
    if point_labels_to_right:
        x_left, x_right = axs.get_xlim()
        axs.set_xlim(right=x_right + (x_right - x_left) * 0.1)

    # Show y axes as percentages is asked
    if y_value_formatter is not None:
        axs.yaxis.set_major_formatter(plt.FuncFormatter(y_value_formatter.format))
        axs.yaxis.set_minor_formatter(plt.FuncFormatter(y_value_formatter.format))
        if secondary_ax is not None:
            secondary_ax.yaxis.set_major_formatter(
                plt.FuncFormatter(y_value_formatter.format)
            )
            secondary_ax.yaxis.set_minor_formatter(
                plt.FuncFormatter(y_value_formatter.format)
            )

    # Show grid lines if specified
    if gridlines is not None:
        axs.grid(axis=gridlines, which="both")

    # Set different markers + print labels
    # Set different markers for each line + get mn/max values + print labels
    markers = ("o", "^", "*", "+", "x", ".", "s", "D", "v", "P", "X", "d")
    max_y_value = None
    min_y_value = None
    for series_index, line in enumerate(axs.get_lines()):
        line.set_marker(markers[series_index % len(markers)])
        label_above_line = True

        for index, row_fieldvalue in enumerate(df.iloc[:, series_index]):
            if pd.isna(row_fieldvalue):
                continue
            if y_value_limit is not None and row_fieldvalue > y_value_limit:
                continue
            if max_y_value is None or row_fieldvalue > max_y_value:
                max_y_value = row_fieldvalue
            if min_y_value is None or row_fieldvalue < min_y_value:
                min_y_value = row_fieldvalue
            if print_labels_on_points is True:
                if y_value_formatter is not None:
                    text = y_value_formatter.format(row_fieldvalue)
                else:
                    text = str(row_fieldvalue)

                if point_labels_to_right:
                    xytext = (5, 0)
                    horizontalalignment = "left"
                else:
                    if label_above_line is True:
                        xytext = (0, 5)
                        label_above_line = False
                    else:
                        xytext = (0, -15)
                        label_above_line = True
                    horizontalalignment = "center"

                axs.annotate(
                    text=text,
                    xy=(index, row_fieldvalue),
                    xytext=xytext,
                    textcoords="offset points",
                    ha=horizontalalignment,
                    fontweight="normal",
                )

    if secondary_ax is not None and secondary_y_df is not None:
        secondary_max_y_value = None
        for series_index, line in enumerate(secondary_ax.get_lines()):
            marker_index = (len(axs.get_lines()) + series_index) % len(markers)
            line.set_marker(markers[marker_index])
            line.set_color("tab:orange")
            label_above_line = False

            for index, row_fieldvalue in enumerate(
                secondary_y_df.iloc[:, series_index]
            ):
                if pd.isna(row_fieldvalue):
                    continue
                if (
                    secondary_max_y_value is None
                    or row_fieldvalue > secondary_max_y_value
                ):
                    secondary_max_y_value = row_fieldvalue
                if print_labels_on_points:
                    if y_value_formatter is not None:
                        text = y_value_formatter.format(row_fieldvalue)
                    else:
                        text = str(row_fieldvalue)
                    if point_labels_to_right:
                        xytext = (5, 0)
                        horizontalalignment = "left"
                    elif label_above_line:
                        xytext = (0, 5)
                        horizontalalignment = "center"
                        label_above_line = False
                    else:
                        xytext = (0, -15)
                        horizontalalignment = "center"
                        label_above_line = True
                    secondary_ax.annotate(
                        text=text,
                        xy=(index, row_fieldvalue),
                        xytext=xytext,
                        textcoords="offset points",
                        ha=horizontalalignment,
                        fontweight="normal",
                    )

        if secondary_max_y_value is not None and secondary_max_y_value > 0:
            secondary_ax.set_ylim(bottom=0, top=secondary_max_y_value * 1.1)
        else:
            secondary_ax.set_ylim(bottom=0, top=1)

    # Set bottom and top values for y axis
    has_overflow = y_value_limit is not None and bool(df.gt(y_value_limit).any().any())
    if max_y_value is not None:
        max_y_value *= 1.1
    elif has_overflow:
        max_y_value = y_value_limit
    if max_y_value is not None and math.isnan(max_y_value) is False:
        if yscale == "log":
            axs.set_ylim(top=max_y_value)
        else:
            axs.set_ylim(bottom=0, top=max_y_value)
    elif yscale != "log":
        axs.set_ylim(bottom=0)

    if has_overflow:
        overflow_count_by_x: dict[int, int] = {}
        plotted_lines = axs.get_lines()
        for x_index, row in enumerate(df.itertuples(index=False, name=None)):
            for series_index, value in enumerate(row):
                if value > y_value_limit:
                    overflow_count = overflow_count_by_x.get(x_index, 0)
                    overflow_count_by_x[x_index] = overflow_count + 1
                    if y_value_formatter is not None:
                        text = y_value_formatter.format(value)
                    else:
                        text = str(value)
                    marker_x = x_index + 0.15
                    marker_y = 1.09 + 0.07 * overflow_count
                    marker_color = (
                        plotted_lines[series_index].get_color()
                        if series_index < len(plotted_lines)
                        else "black"
                    )
                    axs.annotate(
                        text="",
                        xy=(x_index, 1.15),
                        xycoords=("data", "axes fraction"),
                        xytext=(x_index, 1.0),
                        textcoords=("data", "axes fraction"),
                        arrowprops={"arrowstyle": "->"},
                        annotation_clip=False,
                    )
                    axs.plot(
                        marker_x,
                        marker_y,
                        marker=markers[series_index % len(markers)],
                        color=marker_color,
                        linestyle="None",
                        transform=axs.get_xaxis_transform(),
                        clip_on=False,
                    )
                    axs.annotate(
                        text=text,
                        xy=(marker_x, marker_y),
                        xycoords=("data", "axes fraction"),
                        xytext=(8, 0),
                        textcoords="offset points",
                        ha="left",
                        va="center",
                        fontweight="normal",
                        annotation_clip=False,
                    )

    # Reserve room for one legend outside the plot area.
    fig.tight_layout()
    fig.subplots_adjust(right=0.72)
    lines, labels = axs.get_legend_handles_labels()
    if secondary_ax is not None:
        secondary_lines, secondary_labels = secondary_ax.get_legend_handles_labels()
        lines += secondary_lines
        labels += secondary_labels
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_right = max(axis.get_tightbbox(renderer).x1 for axis in fig.axes)
    legend_left = fig.transFigure.inverted().transform((axes_right + 12, 0))[0]
    axs.legend(
        lines,
        labels,
        loc="center left",
        bbox_to_anchor=(legend_left, 0.5),
        bbox_transform=fig.transFigure,
    )
    if has_overflow:
        fig.subplots_adjust(top=overflow_axes_top)
        axs.set_title(axs.get_title(), y=1.15, pad=3)

    # Save the file if it doesn't exist yet
    if not output_path.exists():
        fig.savefig(str(output_path), bbox_inches="tight")
    else:
        # If it exists already, only save it if it has changed
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_output_path = Path(tmp_dir) / output_path.name
            fig.savefig(tmp_output_path, bbox_inches="tight")
            img_new = np.asarray(Image.open(tmp_output_path))
            img_old = np.asarray(Image.open(output_path))
            if not np.array_equal(img_new, img_old):
                shutil.move(tmp_output_path, output_path)

    plt.close(fig)


if __name__ == "__main__":
    results_dir = Path(__file__).resolve().parent / "results_vector_ops"
    # results_dir = Path(__file__).resolve().parent / "results_zonalstats"
    results_path = results_dir / "benchmark_results.csv"
    output_dir = results_dir
    generate_reports(results_path, output_dir)
