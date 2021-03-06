<?php
/*
 * Copyright 2012 Arno Teigseth, Tuomas Jaakola
 * 
 * This file is part of TOE.
 *
 * TOE is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * TOE is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with TOE.  If not, see <http://www.gnu.org/licenses/>.
 *
 */

chdir("..");
include("config.php");
include("archive/archive.php");

$archive = new Archive($cfg['archive_file']);

if (isset($_POST['data'])) {
    // write
    $id = $archive->write($_POST['data']);
    print $id;
}
elseif (isset($_GET['id'])) {
    // read
    $id = $_GET['id'];
    print $archive->read($id);
}

?>
