import csv
import random
from datetime import datetime, timedelta
from django.http import HttpResponse

def random_date(start: datetime, end: datetime):
    delta_days = (end - start).days
    return start + timedelta(days=random.randint(0, delta_days))


def random_datetime(start: datetime, end: datetime):
    delta_seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, delta_seconds))


def generate_cell_value(column, index: int):
    """
    column → CSVJobColumn instance
    index  → satır numarası (1, 2, 3...)
    """

    if column.type == "string":
        return column.example_value.format(i=index)

    if column.type == "int":
        try:
            base = int(column.example_value)
        except ValueError:
            base = 0
        return random.randint(base, base + 100)

    if column.type == "date":
        start = datetime.now() - timedelta(days=365)
        end = datetime.now()
        return random_date(start, end).strftime("%Y-%m-%d")

    if column.type == "datetime":
        start = datetime.now() - timedelta(days=30)
        end = datetime.now()
        return random_datetime(start, end).strftime("%Y-%m-%d %H:%M:%S")

    return ""


def export_csv(job):
    """
    job → CSVJob instance
    return → HttpResponse (CSV download)
    """

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="csv_job_{job.id}.csv"'

    writer = csv.writer(response, delimiter=';')

    columns = job.columns.all()

    # HEADER
    writer.writerow([col.name for col in columns])

    # ROWS
    for i in range(1, job.row_count + 1):
        row = [
            generate_cell_value(col, i)
            for col in columns
        ]
        writer.writerow(row)

    return response
