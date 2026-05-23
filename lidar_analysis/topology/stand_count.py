import numpy as np
def topology_stand_count(point_cloud):
    import pandas as pd
    from .imagepers import persistence
    count = 0
    df = pd.DataFrame(point_cloud, columns = ("x", "y", "z"))

    # Get density by grouping points in a 0.02 (1 / 50) meter grid on the x dimension.
    # The z values are already discritized to each lidar scan.
    round_x = np.floor(point_cloud[:, 0] * 50) / 50
    df["round_x"] = round_x
    pc = df.groupby(["round_x", "z"], as_index=False).size()  # Get the number of points in each round_x-by-z group.

    # Use the groups to create a complete grid of coordinates.
    # When merging, empty cells will be NaN.
    xs = pd.DataFrame(set(pc["round_x"]), columns=("round_x",))
    zs = pd.DataFrame(set(pc["z"]), columns=("z",))
    dims = xs.merge(zs, how='cross')
    grid_as_table = pc.merge(dims, left_on=('round_x', 'z'), right_on=('round_x', 'z'), how='outer')

    grid_as_table = grid_as_table.sort_values(by=['round_x', 'z'], ascending=(False, True))

    im = np.array(grid_as_table['size'])
    im.shape = (len(xs), len(zs))
    nan_inds = np.isnan(im)
    im[nan_inds] = 0

    im = im / np.max(im)
    g0 = persistence(im)


    """
    fig = plt.figure()
    plt.imshow(im, aspect='auto',
            interpolation="nearest",
            extent = [zs['z'].min(), zs['z'].max(), xs['round_x'].min(), xs['round_x'].max()])
    plt.colorbar()
    #plt.show()
    xx, yy = np.mgrid[0:im.shape[0], 0:im.shape[1]]
    #fig = plt.figure()
    #plt.contourf(xx, yy, im, np.arange(0, 255, 20))

    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.set_title("Peristence diagram")
    ax.plot([0, 1], [0, 1], '-', c='grey')
    for i, homclass in enumerate(g0):
        p_birth, bl, pers, p_death = homclass
        if pers <= 0.01:
            continue
        x, y = bl, bl-pers
        ax.plot([x], [y], '.', c='b')
        ax.text(x, y+2, str(i+1), color='b')
    ax.set_xlabel("Birth level")
    ax.set_ylabel("Death level")
    ax.set_xlim((-0.1, 1))
    ax.set_ylim((-0.1, 1))

    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.set_title("Loci of births")
    for i, homclass in enumerate(g0):
        p_birth, bl, pers, p_death = homclass
        if pers < 0.35:
            continue
        y, x = p_birth
        ax.plot([x], [y], '.', c='b')
        ax.text(x, y+0.35, str(i+1), color='b')

    ax.set_xlim((0,im.shape[1]))
    ax.set_ylim((0,im.shape[0]))
    plt.gca().invert_yaxis()

    fig = plt.figure()
    ax = fig.gca(projection='3d')
    ax.plot_surface(xx, yy, im ,rstride=1, cstride=1, cmap=plt.cm.jet,
            linewidth=0)
    plt.show()
    """

    xs = xs.sort_values(by='round_x', ascending=False)
    zs = zs.sort_values(by='z')

    def ind_to_coord(p):
        return (xs['round_x'].iloc[p[0]], zs['z'].iloc[p[1]])

    points = []
    for i, (q, b, per, d) in enumerate(g0):
        points.append(ind_to_coord(q))
        if per < 0.35:
            count = i
            break

    z = point_cloud[:, 2]
    distance = np.max(z) - np.min(z)
    return {'count': count / distance, 'points': points}